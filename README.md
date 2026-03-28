# FotosAI

O FotosAI é uma aplicação local de pesquisa semântica de fotografias. Utiliza modelos de Inteligência Artificial (arquitetura CLIP com visão e texto multilingue) para indexar a tua biblioteca de imagens e permitir a pesquisa através de linguagem natural em português.

## 🌟 Funcionalidades

- **Pesquisa Semântica:** Encontra fotografias descrevendo o que está nelas (ex: "um cão a brincar na relva", "praia com pôr do sol").
- **Indexação Local:** Todo o processamento é feito localmente no teu computador, garantindo total privacidade das tuas fotografias.
- **Suporte para Grandes Bibliotecas:** Concebido para conseguir indexar bibliotecas extensas de imagens.
- **Interface Web Moderna:** Uma interface web elegante (estilo *glassmorphism*) para gerir a indexação e realizar pesquisas.
- **Processamento em Segundo Plano:** Adiciona pastas para indexar e deixa a IA processar as imagens silenciosamente.

## 🛠️ Tecnologias Utilizadas

- **Backend:** Python, FastAPI, Uvicorn
- **Base de Dados:** SQLite (metadados) e ChromaDB (banco de dados vetorial para os *embeddings*)
- **Modelos de IA:** Sentence-Transformers (modelos CLIP) para extrair os *embeddings* de imagem e texto
- **Frontend:** HTML, CSS, JavaScript (Ficheiros estáticos)

## 🚀 Como Instalar e Executar

### Pré-requisitos
- Python 3.8 ou superior instalado.

### Passos para Instalação

1. **Clonar ou transferir o repositório** para a tua máquina local.

2. **Criar um ambiente virtual (Recomendado):**
   ```bash
   python -m venv venv
   ```
   Ativar o ambiente virtual:
   - No Windows: `venv\Scripts\activate`
   - No macOS/Linux: `source venv/bin/activate`

3. **Instalar as dependências:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Iniciar o servidor:**
   ```bash
   python main.py
   ```
   *Alternativamente, podes usar o uvicorn diretamente:*
   ```bash
   uvicorn main:app --host 0.0.0.0 --port 8000
   ```

5. **Aceder à aplicação:**
   Abre o teu navegador e acede a [http://localhost:8000](http://localhost:8000).

## 📂 Como Utilizar

1. **Indexar Pastas:**
   - Na interface web, introduz o caminho completo de uma pasta local que contenha imagens (ex: `C:\Users\Nome\Imagens\Ferias`).
   - Clica em "Iniciar Indexação". A aplicação começará a analisar e a extrair as hiperligações de cada imagem em segundo plano.

2. **Pesquisar Imagens:**
   - Na barra de pesquisa, escreve o que procuras (ex: "carro vermelho").
   - A IA irá comparar o teu texto com as imagens indexadas e apresentar os melhores resultados.

3. **Ver o Estado da Indexação:**
   - A interface mostra o progresso da indexação, indicando quantos ficheiros foram processados e o total encontrado.

## 📝 Licença

Este projeto foi desenvolvido para fins de pesquisa e uso pessoal num ambiente local.
