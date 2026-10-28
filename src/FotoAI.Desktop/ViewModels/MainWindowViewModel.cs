using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using FotoAI.Desktop.Models;
using FotoAI.Desktop.Services;
using System.Collections.ObjectModel;
using System.Threading.Tasks;
using System;
using Microsoft.Extensions.Logging;

namespace FotoAI.Desktop.ViewModels
{
    public partial class MainWindowViewModel : ObservableObject
    {
        private readonly EngineClient _engineClient;
        private readonly PythonEngineRunner _engineRunner;
        private readonly ILogger<MainWindowViewModel> _logger;

        [ObservableProperty]
        private string _searchQuery = string.Empty;

        [ObservableProperty]
        private bool _isBusy;

        [ObservableProperty]
        private string _engineStatusText = "A verificar motor...";

        // Barra de progresso do rodapé
        [ObservableProperty]
        private bool _isStatusProgressVisible;

        [ObservableProperty]
        private bool _isStatusProgressIndeterminate;

        [ObservableProperty]
        private double _statusProgress; // 0..100

        [ObservableProperty]
        private bool _isStatusError;

        public ObservableCollection<SearchResultModel> SearchResults { get; } = new();

        public MainWindowViewModel(EngineClient engineClient, PythonEngineRunner engineRunner,
                                   ILogger<MainWindowViewModel> logger)
        {
            _engineClient = engineClient;
            _engineRunner = engineRunner;
            _logger = logger;
            _ = InitializeSystemAsync();
        }

        private void SetStatus(string text, double progress = -1, bool busy = false, bool error = false)
        {
            EngineStatusText = text;
            IsStatusError = error;
            IsStatusProgressVisible = busy;
            IsStatusProgressIndeterminate = busy && progress < 0;
            StatusProgress = progress >= 0 ? Math.Clamp(progress * 100, 0, 100) : 0;
        }

        private string? EngineCrashMessage()
        {
            if (_engineRunner.StartFailure != null)
                return _engineRunner.StartFailure;
            if (_engineRunner.HasExited)
            {
                var err = _engineRunner.LastErrorLine ?? "sem detalhes (ver log)";
                var hint = err.Contains("ModuleNotFoundError")
                    ? " Faltam dependências: corre o setup_engine.bat em src\\FotoAI.Engine."
                    : "";
                return $"O motor de IA terminou com erro: {err}.{hint}";
            }
            return null;
        }

        private async Task InitializeSystemAsync()
        {
            var sw = System.Diagnostics.Stopwatch.StartNew();
            // O primeiro arranque pode demorar (importar torch, arrancar o Qdrant): até 2 minutos
            while (sw.Elapsed < TimeSpan.FromMinutes(2))
            {
                var crash = EngineCrashMessage();
                if (crash != null)
                {
                    SetStatus(crash, error: true);
                    _logger.LogCritical("Motor Python terminou durante o arranque: {Msg}", crash);
                    return;
                }

                if (await _engineClient.HealthCheckAsync())
                {
                    _ = CheckEngineStatusLoopAsync();
                    return;
                }

                SetStatus($"A arrancar o motor de IA... ({(int)sw.Elapsed.TotalSeconds}s)", busy: true);
                await Task.Delay(500);
            }

            SetStatus("O motor de IA não respondeu em 2 minutos. Vê o log em %LOCALAPPDATA%\\FotoAI\\Logs.", error: true);
            _logger.LogCritical("Motor Python não respondeu ao health check em 2 minutos.");
        }

        private async Task CheckEngineStatusLoopAsync()
        {
            while (true)
            {
                await CheckEngineStatusAsync();
                await Task.Delay(1000); // Polling periódico não-invasivo
            }
        }

        [RelayCommand]
        private async Task SearchAsync()
        {
            if (string.IsNullOrWhiteSpace(SearchQuery)) return;

            IsBusy = true;
            SearchResults.Clear();

            var response = await _engineClient.SearchAsync(SearchQuery);
            if (response?.Results != null)
            {
                foreach (var result in response.Results)
                {
                    SearchResults.Add(result);
                }
            }

            IsBusy = false;
        }

        [RelayCommand]
        private async Task CheckEngineStatusAsync()
        {
            var status = await _engineClient.GetStatusAsync();
            if (status != null)
            {
                bool busy = status.Phase is "SCANNING" or "DB_SYNC" or "MODEL" or "INDEXING";
                string text = string.IsNullOrWhiteSpace(status.Message)
                    ? (status.IsRunning ? $"A indexar {status.FilesProcessed}/{status.TotalFilesFound}" : "Pronto")
                    : status.Message;
                SetStatus(text, status.Progress, busy, error: status.Phase == "FAILED");
            }
            else
            {
                SetStatus(EngineCrashMessage() ?? "Sem resposta do motor de IA (a tentar de novo...)", error: true);
            }
        }

        [RelayCommand]
        private async Task IndexFolderAsync()
        {
            // Dialogo nativo moderno do .NET 8
            var dialog = new Microsoft.Win32.OpenFolderDialog
            {
                Title = "Selecione a pasta de Fotografias para Indexar",
                Multiselect = false
            };

            if (dialog.ShowDialog() == true)
            {
                var folderPath = dialog.FolderName;
                SetStatus($"A pedir a indexação de {System.IO.Path.GetFileName(folderPath)}...", busy: true);

                var success = await _engineClient.IndexFolderAsync(folderPath);

                if (success)
                {
                    // O loop de estado passa a mostrar o progresso real a cada segundo
                    await CheckEngineStatusAsync();
                }
                else
                {
                    SetStatus("Não foi possível iniciar: já há uma indexação a decorrer, ou o motor não respondeu.", error: true);
                }
            }
        }

        [RelayCommand]
        private void OpenImage(string filePath)
        {
            if (string.IsNullOrWhiteSpace(filePath) || !System.IO.File.Exists(filePath)) return;
            try
            {
                new System.Diagnostics.Process { StartInfo = new System.Diagnostics.ProcessStartInfo { FileName = filePath, UseShellExecute = true } }.Start();
            }
            catch (Exception ex) { _logger.LogError(ex, "Erro ao tentar abrir imagem original."); }
        }

        [RelayCommand]
        private void OpenFolder(string filePath)
        {
            if (string.IsNullOrWhiteSpace(filePath) || !System.IO.File.Exists(filePath)) return;
            try
            {
                // Abre o explorador de ficheiros do Windows nativo, com o ficheiro pré-selecionado
                new System.Diagnostics.Process { StartInfo = new System.Diagnostics.ProcessStartInfo { FileName = "explorer.exe", Arguments = $"/select,\"{filePath}\"", UseShellExecute = true } }.Start();
            }
            catch (Exception ex) { _logger.LogError(ex, "Erro ao tentar abrir o explorador de ficheiros local."); }
        }

        [RelayCommand]
        private async Task SearchSimilarAsync(int photoId)
        {
            if (photoId <= 0) return;

            IsBusy = true;
            SearchQuery = "Imagens Semelhantes...";
            SearchResults.Clear();

            var response = await _engineClient.SearchSimilarAsync(photoId);
            if (response?.Results != null)
            {
                foreach (var result in response.Results)
                {
                    SearchResults.Add(result);
                }
            }

            IsBusy = false;
        }

        [RelayCommand]
        private async Task SearchByImageFileAsync()
        {
            var dialog = new Microsoft.Win32.OpenFileDialog
            {
                Title = "Selecione uma imagem para procurar semelhantes",
                Filter = "Imagens|*.jpg;*.jpeg;*.png;*.webp;*.bmp"
            };

            if (dialog.ShowDialog() == true)
            {
                IsBusy = true;
                SearchQuery = $"Semelhante a: {System.IO.Path.GetFileName(dialog.FileName)}";
                SearchResults.Clear();

                var response = await _engineClient.SearchByImageAsync(dialog.FileName);
                if (response?.Results != null)
                {
                    foreach (var result in response.Results)
                    {
                        SearchResults.Add(result);
                    }
                }

                IsBusy = false;
            }
        }

        [RelayCommand]
        private void ManageFolders()
        {
            var window = Microsoft.Extensions.DependencyInjection.ServiceProviderServiceExtensions.GetRequiredService<Views.ManageFoldersWindow>(App.Current.Services);
            window.Owner = System.Windows.Application.Current.MainWindow;
            window.ShowDialog();
        }

        [RelayCommand]
        private void ShowAbout()
        {
            var window = Microsoft.Extensions.DependencyInjection.ServiceProviderServiceExtensions.GetRequiredService<Views.AboutWindow>(App.Current.Services);
            window.Owner = System.Windows.Application.Current.MainWindow;
            window.ShowDialog();
        }
    }
}
