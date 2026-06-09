# Automação Cantina

Sistema de processamento automático de pedidos de compras em cantinaaria com OCR e auditoria integrada.

## O que faz

- **Converte PDF em imagens** usando `pdf2image` e Poppler
- **Extrai texto manuscrito e tabulado** com Google Cloud Vision
- **Identifica matrícula e itens** com regex inteligente
- **Aplica regras de corte** baseadas em prioridade e saldo disponível
- **Gera relatório de compras aprovadas** em Excel
- **Registra auditoria completa** em log (sem poluir a saída)

## Dependências do Sistema

### Poppler (obrigatório)

O `pdf2image` requer [Poppler](https://poppler.freedesktop.org/) para converter PDFs em imagens.

**Windows:**
```bash
# Com Chocolatey
choco install poppler-cpp

# Ou download manual: https://github.com/oschwartz10612/poppler-windows/releases/
# Após instalar, adicione a pasta bin ao PATH ou defina:
set POPPLER_PATH=C:\caminho\para\poppler\Library\bin
```

**macOS:**
```bash
brew install poppler
```

**Linux (Debian/Ubuntu):**
```bash
sudo apt-get install poppler-utils
```

### Credenciais Google Cloud

1. Crie um projeto no [Google Cloud Console](https://console.cloud.google.com/)
2. Ative a API **Cloud Vision**
3. Crie uma Service Account e baixe o arquivo JSON
4. Salve como `peculio-compras-a86b00969829.json` na raiz do projeto

## Instalação

1. Clone o repositório:
```bash
git clone https://github.com/seu-usuario/automacao_cantina.git
cd automacao_cantina
```

2. Instale as dependências Python:
```bash
pip install -r requirements.txt
```

3. Configure o Poppler (veja seção acima)

## Arquivos de Entrada

- **`saldo_presos-2.xlsx`**: Planilha com matrícula e saldo disponível
  - Colunas: `MATRICULA`, `DISPONIVEL`
  
- **`DISTRIBUICAO.xlsx`**: Catálogo de produtos
  - Colunas: `CODIGO_2`, `DESCRICAO`, `VALOR`, `corte/prioridade`
  - Nota: Caminho é fixo em `C:\Users\PECULIORENATO\Documents\Python\AutoPec\DISTRIBUICAO.xlsx`
  
- **`folhas.pdf`**: Formulários manuscritos escaneados
  - Esperado: uma matrícula e itens por página
  - Formato: `MATRICULA: 1173062` seguido de linhas com `CODIGO QUANTIDADE`

## Executar

```bash
python main.py
```

### Saída

- **Console (INFO e acima)**: Resumo do processamento, avisos e erros
- **Arquivo `automacao_cantina.log`**: Registro completo (DEBUG e acima) para auditoria
- **`COMPRAS_PRONTAS_GPU.xlsx`**: Compras aprovadas com valores

## Estrutura da Saída (Excel)

| Coluna | Descrição |
|--------|-----------|
| `Matricula` | ID do interno |
| `Codigo_Produto` | Código do item no catálogo |
| `Descricao` | Nome do produto |
| `Qtde_Aprovada` | Unidades aprovadas |
| `Valor_Unitario` | Preço por unidade |
| `Total_Item` | Subtotal |

## Algoritmo de Corte

1. **Ordena** por prioridade (ascendente) e preço (menor primeiro)
2. **Round-robin**: aprova itens 1 unidade por vez respeitando saldo
3. **Evita desperdício**: item só é aprovado se há saldo para unidade completa

## Auditoria

Todos os eventos são registrados em `automacao_cantina.log`:
- Carregamento de bases
- Matrícula detectada por página
- Itens lidos e validados
- Decisões de aprovação
- Erros com stack trace completo

**Nível DEBUG**: Detalhes de cada decisão
**Nível INFO**: Resumo por página e resultado final
**Nível WARNING**: Páginas com problemas
**Nível ERROR**: Falhas críticas

## Troubleshooting

### `PDFInfoNotInstalledError`
- Poppler não está no PATH
- Solução: Instale Poppler (veja acima) ou defina `POPPLER_PATH`

### `FileNotFoundError` nas bases
- Verificar se `saldo_presos-2.xlsx` existe
- Verificar se path para `DISTRIBUICAO.xlsx` está correto (arquivo fixo)

### Google Cloud Vision falha
- Verificar credenciais JSON
- Verificar se API está ativada na console
- Verificar quotas do projeto

## Licença

MIT

## Autor

Criado para automação de cantinaaria.
