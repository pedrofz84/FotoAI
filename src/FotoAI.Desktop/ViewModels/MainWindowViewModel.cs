using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using FotoAI.Desktop.Models;
using FotoAI.Desktop.Services;
using System.Collections.ObjectModel;
using System.Threading.Tasks;
using System;
using System.Linq;
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

        // Filtro por ano: "Todos" ou um ano com fotos
        public const string AllYears = "Todos";
        public ObservableCollection<string> Years { get; } = new() { AllYears };

        [ObservableProperty]
        private string _yearFrom = AllYears;

        [ObservableProperty]
        private string _yearTo = AllYears;

        [ObservableProperty]
        private string _yearFilterHint = "";

        // Ordenação dos resultados (feita aqui, sem voltar a perguntar ao motor)
        public const string SortRelevance = "Relevância";
        public const string SortNewest = "Mais recentes";
        public const string SortOldest = "Mais antigas";
        public const string SortName = "Nome";
        public string[] SortOptions { get; } = { SortRelevance, SortNewest, SortOldest, SortName };

        [ObservableProperty]
        private string _sortOrder = SortRelevance;

        private List<SearchResultModel> _lastResults = new();

        partial void OnSortOrderChanged(string value) => ApplySort();

        private void ApplySort()
        {
            IEnumerable<SearchResultModel> sorted = SortOrder switch
            {
                // Fotos sem data vão sempre para o fim
                SortNewest => _lastResults.OrderBy(r => r.CaptureDate == null)
                                          .ThenByDescending(r => r.CaptureDate)
                                          .ThenBy(r => r.FileName, StringComparer.CurrentCultureIgnoreCase),
                SortOldest => _lastResults.OrderBy(r => r.CaptureDate == null)
                                          .ThenBy(r => r.CaptureDate)
                                          .ThenBy(r => r.FileName, StringComparer.CurrentCultureIgnoreCase),
                SortName => _lastResults.OrderBy(r => r.FileName, StringComparer.CurrentCultureIgnoreCase),
                _ => _lastResults.OrderByDescending(r => r.Score),
            };
            SearchResults.Clear();
            foreach (var r in sorted)
                SearchResults.Add(r);
        }

        // Para repetir a última pesquisa quando o filtro muda
        private Func<Task>? _lastSearch;
        private bool _wasBusy;
        private bool _reloadingYears;

        private static int? ParseYear(string value) => int.TryParse(value, out var y) ? y : null;
        private int? FromYear => ParseYear(YearFrom);
        private int? ToYear => ParseYear(YearTo);

        partial void OnYearFromChanged(string value) => _ = RepeatLastSearchAsync();
        partial void OnYearToChanged(string value) => _ = RepeatLastSearchAsync();
        // (o WPF pode pôr null quando a lista de anos é recarregada; ParseYear trata disso)

        private async Task RepeatLastSearchAsync()
        {
            if (_lastSearch != null && !IsBusy && !_reloadingYears)
                await _lastSearch();
        }

        private async Task RunSearchAsync(Func<Task<SearchResponseModel?>> search)
        {
            IsBusy = true;
            SearchResults.Clear();
            var response = await search();
            _lastResults = response?.Results?.ToList() ?? new List<SearchResultModel>();
            ApplySort();
            IsBusy = false;
        }

        private async Task LoadYearsAsync()
        {
            var response = await _engineClient.GetYearsAsync();
            if (response == null) return;
            YearFilterHint = response.WithoutDate > 0
                ? $"Com filtro de ano, as {response.WithoutDate:N0} fotos sem data ficam de fora."
                : "";
            var keepFrom = YearFrom;
            var keepTo = YearTo;
            var years = response.Years.Select(y => y.Year.ToString()).ToList();
            if (Years.Skip(1).SequenceEqual(years)) return;

            // Ao limpar a lista as ComboBox largam a seleção; não pode disparar pesquisas
            _reloadingYears = true;
            try
            {
                Years.Clear();
                Years.Add(AllYears);
                foreach (var y in years) Years.Add(y);
                YearFrom = Years.Contains(keepFrom) ? keepFrom : AllYears;
                YearTo = Years.Contains(keepTo) ? keepTo : AllYears;
            }
            finally
            {
                _reloadingYears = false;
            }
        }

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
                    await LoadYearsAsync();
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
            var query = SearchQuery;
            _lastSearch = () => RunSearchAsync(() => _engineClient.SearchAsync(query, yearFrom: FromYear, yearTo: ToYear));
            await _lastSearch();
        }

        [RelayCommand]
        private async Task CheckEngineStatusAsync()
        {
            var status = await _engineClient.GetStatusAsync();
            if (status != null)
            {
                bool busy = status.Phase is "SCANNING" or "DB_SYNC" or "MODEL" or "INDEXING";
                // Acabou uma indexação: pode haver anos novos
                if (_wasBusy && !busy) await LoadYearsAsync();
                _wasBusy = busy;
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
        private async Task ImportLightroomAsync()
        {
            var dialog = new Microsoft.Win32.OpenFileDialog
            {
                Title = "Escolha o catálogo do Lightroom (feche o Lightroom antes)",
                Filter = "Catálogo Lightroom|*.lrcat"
            };

            if (dialog.ShowDialog() == true)
            {
                SetStatus($"A pedir a importação de {System.IO.Path.GetFileName(dialog.FileName)}...", busy: true);
                var error = await _engineClient.ImportLightroomAsync(dialog.FileName);
                if (error == null)
                    await CheckEngineStatusAsync();
                else
                    SetStatus(error, error: true);
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
            SearchQuery = "Imagens Semelhantes...";
            _lastSearch = () => RunSearchAsync(() => _engineClient.SearchSimilarAsync(photoId, yearFrom: FromYear, yearTo: ToYear));
            await _lastSearch();
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
                var file = dialog.FileName;
                SearchQuery = $"Semelhante a: {System.IO.Path.GetFileName(file)}";
                _lastSearch = () => RunSearchAsync(() => _engineClient.SearchByImageAsync(file, yearFrom: FromYear, yearTo: ToYear));
                await _lastSearch();
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
