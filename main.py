import os
import io
import re
import logging
import pandas as pd
from google.cloud import vision
from pdf2image import convert_from_path
from pdf2image.exceptions import PDFInfoNotInstalledError

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
    # Saldos
    df_saldos = pd.read_excel('saldo_presos-2.xlsx', sheet_name='Planilha1')
    saldos_dict = df_saldos.set_index('MATRICULA')['DISPONIVEL'].to_dict()

    # Catálogo
    df_dist = pd.read_excel(r'C:\Users\PECULIORENATO\Documents\Python\AutoPec\DISTRIBUICAO.xlsx', sheet_name='PVALP1')
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
    """Envia uma imagem da página para a API do Google e retorna o texto completo."""
    client = vision.ImageAnnotatorClient()
    
    # Converte a imagem PIL para bytes
    byte_array = io.BytesIO()
    imagem.save(byte_array, format='PNG')
    content = byte_array.getvalue()

    image_vision = vision.Image(content=content)
    
    # DOCUMENT_TEXT_DETECTION é a magia que lê tabelas e caligrafia juntas
    response = client.document_text_detection(image=image_vision)
    
    if response.error.message:
        raise Exception(f'Erro na API do Google: {response.error.message}')
        
    return response.full_text_annotation.text

def processar_pedido_ia(texto_extraido, catalogo_dict):
    """Encontra a matrícula e os itens + quantidades manuscritas no texto lido pelo Google."""
    matricula = None
    itens_pedidos = []
    
    # Procura a matrícula (ex: MATRICULA: 1173062)
    match_mat = re.search(r'MATRICULA:\s*(\d+)', texto_extraido, re.IGNORECASE)
    if match_mat:
        matricula = int(match_mat.group(1))
        logger.debug('Matrícula identificada no texto: %s', matricula)

    # Procura os itens. O padrão esperado é o código (6 dígitos) seguido de um número (quantidade)
    # Ex: "136485 2 ACHOCOLATADO..."
    linhas = texto_extraido.split('\n')
    for linha in linhas:
        # Busca 6 dígitos, um ou mais espaços, e 1 a 2 dígitos numéricos isolados
        match_item = re.search(r'(\d{6})\s+(\d{1,2})(?:\s+|$)', linha)
        if match_item:
            cod = match_item.group(1)
            qtde = int(match_item.group(2))
            
            # Só adiciona se o preso pediu > 0 e o código existir no catálogo do mês
            if qtde > 0 and cod in catalogo_dict:
                itens_pedidos.append({
                    'codigo': cod,
                    'qtde_lida': qtde
                })
                logger.debug('Item detectado no texto: código=%s qtde=%s', cod, qtde)
            elif qtde > 0:
                logger.debug('Item encontrado mas não válido no catálogo: código=%s qtde=%s', cod, qtde)
                
    return matricula, itens_pedidos

def aplicar_regras_compra(matricula, itens_pedidos, saldos_dict, catalogo_dict):
    """Executa o algoritmo da mochila (corte por prioridade e saldo)."""
    saldo_disponivel = saldos_dict.get(matricula, 0.0)
    logger.debug('Saldo disponível para matrícula %s: %s', matricula, saldo_disponivel)
    
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
            
    # Ordena: 1º Prioridade (1 é melhor), 2º Menor Preço
    pedido_ordenado = sorted(pedido_enriquecido, key=lambda x: (x['Prioridade'], x['Preco_Un']))
    
    saldo_restante = saldo_disponivel
    houve_alteracao = True
    
    # Motor de Corte (Round-Robin)
    while houve_alteracao and saldo_restante > 0:
        houve_alteracao = False
        for item in pedido_ordenado:
            if item['Qtde_Aprovada'] < item['Qtde_Pedida'] and saldo_restante >= item['Preco_Un']:
                item['Qtde_Aprovada'] += 1
                saldo_restante -= item['Preco_Un']
                saldo_restante = round(saldo_restante, 2)
                houve_alteracao = True
                logger.debug('Aprovado 1 unidade de %s para matrícula %s; saldo restante %s', item['Codigo'], matricula, saldo_restante)
                
    # Prepara a saída final apenas com o que foi aprovado
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
            logger.debug('Compra aprovada: %s x %s para matrícula %s', item['Codigo'], item['Qtde_Aprovada'], matricula)
    
    return resultado_aprovado

def obter_poppler_path():
    poppler_path = os.environ.get('POPPLER_PATH')
    if poppler_path:
        logger.debug('Usando POPPLER_PATH: %s', poppler_path)
    return poppler_path


def iniciar_esteira():
    saldos_dict, catalogo_dict = carregar_bases()
    
    arquivo_pdf = 'folhas.pdf'
    logger.info('Convertendo o arquivo %s em imagens...', arquivo_pdf)
    poppler_path = obter_poppler_path()
    try:
        caminho_poppler = r"C:\Users\PECULIORENATO\OneDrive\Documentos\Python\poppler\poppler-26.02.0\Library\bin"
        paginas_imagem = convert_from_path(arquivo_pdf, dpi=300, poppler_path=caminho_poppler)
    except PDFInfoNotInstalledError as e:
        msg = (
            'Poppler não encontrado. Instale Poppler e adicione-o ao PATH, '
            'ou defina POPPLER_PATH para a pasta bin do Poppler.'
        )
        logger.error(msg)
        raise RuntimeError(msg) from e
    logger.info('Arquivo convertido em %d páginas.', len(paginas_imagem))
    
    compras_gerais_gpu = []
    
    for i, imagem in enumerate(paginas_imagem):
        logger.info('Processando Página %d no Google Cloud Vision...', i+1)
        
        try:
            texto_google = extrair_texto_google_vision(imagem)
            logger.debug('Texto extraído da página %d: %s', i+1, texto_google[:750].replace('\n', ' '))
            matricula, itens_pedidos = processar_pedido_ia(texto_google, catalogo_dict)
            
            if not matricula:
                logger.warning('Página %d: matrícula não encontrada.', i+1)
                continue
                
            if not itens_pedidos:
                logger.warning('Página %d: matrícula %s - nenhum item com quantidade detectado.', i+1, matricula)
                continue
                
            itens_aprovados = aplicar_regras_compra(matricula, itens_pedidos, saldos_dict, catalogo_dict)
            compras_gerais_gpu.extend(itens_aprovados)
            
            logger.info('Página %d: matrícula %s | itens pedidos=%d | itens aprovados=%d', i+1, matricula, len(itens_pedidos), len(itens_aprovados))
            
        except Exception as e:
            logger.error('Erro na página %d: %s', i+1, e, exc_info=True)
            
    # Geração do Arquivo de Saída
    if compras_gerais_gpu:
        df_final = pd.DataFrame(compras_gerais_gpu)
        nome_saida = 'COMPRAS_PRONTAS_GPU.xlsx'
        df_final.to_excel(nome_saida, index=False)
        logger.info('Arquivo de saída gerado: %s (%d linhas)', nome_saida, len(df_final))
    else:
        logger.info('Nenhuma compra aprovada em todo o lote.')

if __name__ == "__main__":
    iniciar_esteira()