# FotoAI 📸

Pesquisa semântica de fotografias, 100% local. Descreves o que te lembras em português (ex: *"um cão na praia ao pôr do sol"*) e o FotoAI encontra as fotos mais parecidas, sem tags nem serviços na nuvem. Também encontra fotos semelhantes a uma foto que escolhas.

A aplicação é composta por duas partes:

- **FotoAI.Desktop** (`src/FotoAI.Desktop`): interface Windows em WPF / .NET 8.
- **FotoAI.Engine** (`src/FotoAI.Engine`): motor em Python (FastAPI) que indexa as fotos e responde às pesquisas. A app desktop arranca-o e fecha-o sozinha.

## Como funciona

- **Modelos CLIP** (Sentence-Transformers): as imagens são codificadas com `clip-ViT-B-32` e o texto com `clip-ViT-B-32-multilingual-v1`, que partilham o mesmo espaço vetorial de 512 dimensões e por isso permitem pesquisar em português.
- **Qdrant** guarda os vetores e faz a pesquisa por semelhança de coseno.
- **SQLite** guarda as pastas indexadas, os metadados das fotos e o estado de cada uma, para que voltar a sincronizar uma pasta só processe o que mudou.
- Os dados ficam em `%LOCALAPPDATA%\FotoAI` (base de dados, vetores, miniaturas, previews e logs).

**Formatos suportados:** JPEG, PNG, WebP, BMP, TIFF, HEIC e RAW (CR2, CR3, NEF, ARW, DNG, ORF, RW2, RAF, PEF...). Nos RAW usa-se a pré-visualização JPEG embutida; se for muito pequena, o RAW é revelado em meia resolução. As pastas `.lrdata` do Lightroom são ignoradas.

## Preparar o ambiente

### Motor Python

O mais simples é correr `src/FotoAI.Engine/setup_engine.bat`, que cria o `.venv` e instala o torch com CUDA se houver GPU NVIDIA.

Manualmente:
```bash
cd src/FotoAI.Engine
python -m venv .venv
.venv\Scripts\activate
# Com GPU NVIDIA, instala primeiro o torch com CUDA:
pip install torch --index-url https://download.pytorch.org/whl/cu124
pip install -r requirements.txt
```
A app desktop encontra o `.venv` sozinha. Também podes apontar para outro Python com a variável `FOTOAI_PYTHON`.

### Servidor Qdrant

Recomendado acima de ~20 mil fotos. Descarrega o `qdrant-x86_64-pc-windows-msvc.zip` em https://github.com/qdrant/qdrant/releases e coloca o `qdrant.exe` em `src/FotoAI.Engine/qdrant/`. O motor arranca-o sozinho, com os dados em `%LOCALAPPDATA%\FotoAI\Vectors\qdrant_server`, e fecha-o quando a app termina.

Se já tiveres um servidor a correr (por exemplo com o `docker-compose.yml` deste repositório), o motor usa esse. Sem o `qdrant.exe`, o motor usa o modo local e avisa no log. Para forçar o modo local: `FOTOAI_QDRANT_URL=local`.

## Correr em desenvolvimento

1. Abre `src/FotoAI.Desktop` no Visual Studio e carrega em F5 (ou `dotnet run`).
2. A app lança o motor Python em segundo plano. O rodapé mostra "A arrancar Motor..." e depois "IA Pronta e Ligada" quando os modelos estão carregados. Na primeira vez os modelos (~1,1 GB) são descarregados.
3. Ao fechar a janela, o processo Python é terminado.

## Como usar

- **Indexar Pasta...** escolhe uma pasta de fotografias. As fotos novas são processadas em lotes; se a pasta já tiver sido indexada, só é processado o que mudou.
- **Pesquisar**: escreve uma descrição e carrega em Enter.
- **📷**: pesquisa usando uma imagem do disco.
- **Botão direito numa foto**: abrir o original, abrir a pasta ou procurar fotos semelhantes.
- **Gerir Pastas**: remove pastas da biblioteca.

## Afinação

Variáveis de ambiente do motor:

| Variável | Para quê |
|---|---|
| `FOTOAI_BATCH_SIZE` | Imagens por lote enviadas ao CLIP (por omissão 32) |
| `FOTOAI_LOADER_WORKERS` | Threads de leitura de ficheiros |
| `FOTOAI_NETWORK_LOADER_WORKERS` | Threads de leitura em pastas de rede (por omissão 12) |
| `FOTOAI_QDRANT_URL` | Endereço do Qdrant, ou `local` |

As previews HD só são geradas quando abres a foto. Uma indexação pode ser parada a meio (`POST /api/index/cancel`) e o progresso fica guardado.

## Recomeçar do zero

Fecha a app e apaga a pasta `%LOCALAPPDATA%\FotoAI`.

## Compilar o instalador

1. **Motor:** `cd src/FotoAI.Engine` e `pyinstaller --name engine --onedir main.py`
2. **App:** `cd src/FotoAI.Desktop` e `dotnet publish -c Release -r win-x64 --self-contained true`
3. **Setup:** abre `installer/build_installer.iss` no Inno Setup e carrega em Compile.

O instalador ainda não foi testado num PC sem Python.

## Licença

Distribuído sob a licença MIT. Vê o ficheiro [LICENSE](LICENSE).
