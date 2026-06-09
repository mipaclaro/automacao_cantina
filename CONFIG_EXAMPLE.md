# Arquivo de Configuração de Ambiente

## Variáveis de Ambiente Opcionais

### POPPLER_PATH
Define o caminho para a pasta bin do Poppler, caso não esteja no PATH do sistema.

Windows:
```
set POPPLER_PATH=C:\Program Files\poppler\Library\bin
```

Bash/Linux/macOS:
```
export POPPLER_PATH=/usr/local/bin
```

### GOOGLE_APPLICATION_CREDENTIALS
Já configurado no código para `peculio-compras-a86b00969829.json`
Se usar outro arquivo, altere a linha em main.py ou defina:
```
set GOOGLE_APPLICATION_CREDENTIALS=caminho/para/seu/arquivo.json
```

## Estrutura Esperada de Arquivos

```
automacao_cantina/
├── main.py                          # Script principal
├── requirements.txt                 # Dependências Python
├── README.md                        # Documentação
├── .gitignore                       # Arquivos a ignorar no Git
├── saldo_presos-2.xlsx             # Entrada: saldos dos internos (NÃO subir para Git)
├── folhas.pdf                       # Entrada: PDFs escaneados (NÃO subir para Git)
├── peculio-compras-a86b00969829.json # Credenciais Google (NÃO subir para Git)
├── automacao_cantina.log           # Log gerado (NÃO subir para Git)
└── COMPRAS_PRONTAS_GPU.xlsx        # Saída gerada (NÃO subir para Git)
```

Nota: DISTRIBUICAO.xlsx é carregado de caminho fixo externo.
