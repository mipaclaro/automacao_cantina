import os
import io
import re
import logging
import pandas as pd
from google.cloud import vision
from pdf2image import convert_from_path
from pdf2image.exceptions import PDFInfoNotInstalledError
import json

# 1. AUTENTICAÇÃO DO GOOGLE
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "peculio-compras-a86b00969829.json"

LOG_FILE = 'automacao_cantina.log'
logger = logging.getLogger('automacao_cantina')
logger.setLevel(logging.DEBUG)

formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
file_handler = logging.FileHandler(LOG_FILE, encoding='utf-8')
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(formatter)

stream_handler = logging.StreamHandler()
stream_handler.setLevel(logging.INFO)
stream_handler.setFormatter(formatter)

logger.addHandler(file_handler)
logger.addHandler(stream_handler)
logger.propagate = False

def carregar_bases():
    logger.info("Carregando bases de dados...")
    df_saldos = pd.read_excel('saldo_presos-2.xlsx', sheet_name='Planilha1')
    saldos_dict = df_saldos.set_index('MATRICULA')['DISPONIVEL'].to_dict()

    df_dist = pd.read_excel('DISTRIBUICAO.xlsx', sheet_name='PVALP1')
    df_dist['CODIGO_2'] = df_dist['CODIGO_2'].astype(str).str.strip()
    logger.debug('Bases carregadas: %d saldos, %d itens no catálogo', len(df_saldos), len(df_dist))

    catalogo_dict = {}
    for _, row in df_dist.iterrows():
        cod = str(row['CODIGO_2'])
        if cod != 'nan':
            catalogo_dict[cod] = {
                'descricao': row['DESCRICAO'],
                'preco': float(row['VALOR']),
                'prioridade': int(row['corte/prioridade'])
            }
    return saldos_dict, catalogo_dict

def extrair_texto_google_vision(imagem):
    """Envia uma imagem da página para a API do Google e retorna a resposta completa."""
    client = vision.ImageAnnotatorClient()

    byte_array = io.BytesIO()
    imagem.save(byte_array, format='PNG')
    content = byte_array.getvalue()

    image_vision = vision.Image(content=content)
    response = client.document_text_detection(image=image_vision)

    if response.error.message:
        raise Exception(f'Erro na API do Google: {response.error.message}')

    return response

def salvar_debug_vision(response, num_pagina):
    texto_completo = ""
    if response.full_text_annotation:
        texto_completo = response.full_text_annotation.text or ""

    with open(f'vision_texto_pagina_{num_pagina}.txt', 'w', encoding='utf-8') as f:
        f.write(texto_completo)

    palavras = []
    numeros = []

    if not response.full_text_annotation:
        return

    for page in response.full_text_annotation.pages:
        for block in page.blocks:
            for paragraph in block.paragraphs:
                for word in paragraph.words:
                    texto = ''.join(symbol.text for symbol in word.symbols)
                    vertices = word.bounding_box.vertices

                    x_vals = [v.x for v in vertices]
                    y_vals = [v.y for v in vertices]

                    x_min = min(x_vals)
                    x_max = max(x_vals)
                    y_min = min(y_vals)
                    y_max = max(y_vals)

                    registro = {
                        'texto': texto,
                        'x_min': x_min,
                        'x_max': x_max,
                        'y_min': y_min,
                        'y_max': y_max,
                        'centro_x': round((x_min + x_max) / 2, 2),
                        'centro_y': round((y_min + y_max) / 2, 2),
                        'largura': x_max - x_min,
                        'altura': y_max - y_min
                    }

                    palavras.append(registro)

                    if re.fullmatch(r'[\d.,/:;-]+', texto):
                        numeros.append(registro)

    pd.DataFrame(palavras).to_csv(
        f'vision_palavras_pagina_{num_pagina}.csv',
        index=False,
        encoding='utf-8-sig'
    )

    pd.DataFrame(numeros).to_csv(
        f'vision_numeros_pagina_{num_pagina}.csv',
        index=False,
        encoding='utf-8-sig'
    )

    with open(f'vision_resumo_pagina_{num_pagina}.json', 'w', encoding='utf-8') as f:
        json.dump({
            'pagina': num_pagina,
            'texto_len': len(texto_completo),
            'qtd_palavras': len(palavras),
            'qtd_numeros': len(numeros)
        }, f, ensure_ascii=False, indent=2)

def processar_pagina_com_coordenadas(imagem, catalogo_dict):
    client = vision.ImageAnnotatorClient()
    byte_array = io.BytesIO()
    imagem.save(byte_array, format='PNG')
    content = byte_array.getvalue()
    
    image_vision = vision.Image(content=content)
    response = client.document_text_detection(image=image_vision)
    
    if response.error.message:
        raise Exception(f'Erro na API do Google: {response.error.message}')
        
    palavras = []
    for page in response.full_text_annotation.pages:
        for block in page.blocks:
            for paragraph in block.paragraphs:
                for word in paragraph.words:
                    texto = ''.join([symbol.text for symbol in word.symbols])
                    vertices = word.bounding_box.vertices
                    x_min = min(v.x for v in vertices)
                    x_max = max(v.x for v in vertices)
                    y_min = min(v.y for v in vertices)
                    y_max = max(v.y for v in vertices)
                    
                    texto_limpo = re.sub(r'[^\d]', '', texto) 
                    
                    if texto_limpo: 
                        palavras.append({
                            'texto': texto_limpo,
                            'x_min': x_min,
                            'x_max': x_max,
                            'centro_y': (y_min + y_max) / 2
                        })

    if not palavras:
        return None, []

    itens_pedidos = []

    # 1. Divide as palavras da esquerda e direita (porque tem 2 tabelas lado a lado)
    meio_da_pagina = max(p['x_max'] for p in palavras) / 2
    esquerda = [p for p in palavras if p['x_max'] < meio_da_pagina]
    direita = [p for p in palavras if p['x_min'] >= meio_da_pagina]

    def analisar_metade(lista_palavras):
        codigos = [p for p in lista_palavras if 5 <= len(p['texto']) <= 6 and p['texto'] in catalogo_dict]
        
        for cod in codigos:
            linha_y = cod['centro_y']
            
            candidatos_qtde = []
            for p in lista_palavras:
                # É um número manuscrito? (até 3 digitos)
                if len(p['texto']) <= 3:
                    # O preso escreveu na mesma linha? (Tolerância ALTA de 35 pixels p/ quem tem letra torta)
                    mesma_linha = abs(p['centro_y'] - linha_y) < 35 
                    # O número está DEPOIS do código impresso? (Não importa se ele rabiscou em cima do nome do produto)
                    logo_a_direita = p['x_min'] > cod['x_max']
                    
                    if mesma_linha and logo_a_direita:
                        candidatos_qtde.append(p)
            
            if candidatos_qtde:
                # O primeiro número que ele achar pra direita na mesma linha, ele assume que é a quantidade
                candidatos_qtde.sort(key=lambda x: x['x_min'])
                qtde_lida = int(candidatos_qtde[0]['texto'])
                
                # Regra final contra lixo do OCR (ex: lê um código de barras como 99)
                if 0 < qtde_lida <= 60: 
                    itens_pedidos.append({
                        'codigo': cod['texto'],
                        'qtde_lida': qtde_lida
                    })
                    logger.debug(f"Achei! Cod: {cod['texto']} | Qtde: {qtde_lida}")

    analisar_metade(esquerda)
    analisar_metade(direita)

    # Matrícula
    matricula = None
    for p in palavras:
        if len(p['texto']) == 6 and p['centro_y'] < 500: 
            matricula = int(p['texto'])
            break

    return matricula, itens_pedidos

def aplicar_regras_compra(matricula, itens_pedidos, saldos_dict, catalogo_dict):
    saldo_disponivel = saldos_dict.get(matricula, 0.0)
    
    pedido_enriquecido = []
    for item in itens_pedidos:
        cod = item['codigo']
        info = catalogo_dict[cod]
        pedido_enriquecido.append({
            'Codigo': cod,
            'Descricao': info['descricao'],
            'Qtde_Pedida': item['qtde_lida'],
            'Preco_Un': info['preco'],
            'Prioridade': info['prioridade'],
            'Qtde_Aprovada': 0
        })

    pedido_ordenado = sorted(pedido_enriquecido, key=lambda x: (x['Prioridade'], x['Preco_Un']))
    saldo_restante = saldo_disponivel
    houve_alteracao = True

    while houve_alteracao and saldo_restante > 0:
        houve_alteracao = False
        for item in pedido_ordenado:
            if item['Qtde_Aprovada'] < item['Qtde_Pedida'] and saldo_restante >= item['Preco_Un']:
                item['Qtde_Aprovada'] += 1
                saldo_restante -= item['Preco_Un']
                saldo_restante = round(saldo_restante, 2)
                houve_alteracao = True
                
    resultado_aprovado = []
    for item in pedido_ordenado:
        if item['Qtde_Aprovada'] > 0:
            resultado_aprovado.append({
                'Matricula': matricula,
                'Codigo_Produto': item['Codigo'],
                'Descricao': item['Descricao'],
                'Qtde_Aprovada': item['Qtde_Aprovada'],
                'Valor_Unitario': item['Preco_Un'],
                'Total_Item': round(item['Qtde_Aprovada'] * item['Preco_Un'], 2)
            })

    return resultado_aprovado

def obter_poppler_path():
    poppler_path = os.environ.get('POPPLER_PATH')
    if not poppler_path:
        poppler_path = r"C:\Users\rclar\Documents\Python\poppler-26.02.0\Library\bin"
    return poppler_path

def iniciar_esteira():
    saldos_dict, catalogo_dict = carregar_bases()
    arquivo_pdf = 'folhas.pdf'
    logger.info('Convertendo o arquivo...')
    
    poppler_path = obter_poppler_path()
    try:
        paginas_imagem = convert_from_path(arquivo_pdf, dpi=300, poppler_path=poppler_path)
    except Exception as e:
        raise RuntimeError("Erro Poppler") from e
        
    compras_gerais_gpu = []

    for i, imagem in enumerate(paginas_imagem):
        try:
            response = extrair_texto_google_vision(imagem)
            salvar_debug_vision(response, i + 1)

            matricula, itens_pedidos = processar_pagina_com_coordenadas(imagem, catalogo_dict)

            if not matricula:
                logger.warning('Página %d: matrícula não encontrada.', i + 1)
                continue

            if not itens_pedidos:
                logger.warning('Página %d: matrícula %s - nenhum item detectado.', i + 1, matricula)
                continue

            itens_aprovados = aplicar_regras_compra(matricula, itens_pedidos, saldos_dict, catalogo_dict)
            compras_gerais_gpu.extend(itens_aprovados)

            logger.info(
                'Página %d: matrícula %s | itens pedidos=%d | itens aprovados=%d',
                i + 1, matricula, len(itens_pedidos), len(itens_aprovados)
            )

        except Exception as e:
            logger.error('Erro na página %d: %s', i + 1, e)

    if compras_gerais_gpu:
        df_final = pd.DataFrame(compras_gerais_gpu)
        df_final.to_excel('COMPRAS_PRONTAS_GPU.xlsx', index=False)
        logger.info('Arquivo de saída gerado com SUCESSO.')

if __name__ == "__main__":
    iniciar_esteira()