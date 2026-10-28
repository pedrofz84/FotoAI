using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using FotoAI.Desktop.Models;
using FotoAI.Desktop.Services;
using System.Collections.ObjectModel;
using System.Threading.Tasks;

namespace FotoAI.Desktop.ViewModels
{
    public partial class ManageFoldersViewModel : ObservableObject
    {
        private readonly EngineClient _engineClient;

        public ObservableCollection<FolderResponseItem> Folders { get; } = new();

        [ObservableProperty]
        private bool _isBusy;

        public ManageFoldersViewModel(EngineClient engineClient)
        {
            _engineClient = engineClient;
        }

        public async Task LoadFoldersAsync()
        {
            IsBusy = true;
            Folders.Clear();
            var response = await _engineClient.GetFoldersAsync();
            if (response?.Folders != null)
            {
                foreach (var folder in response.Folders)
                {
                    Folders.Add(folder);
                }
            }
            IsBusy = false;
        }

        [RelayCommand]
        private async Task SyncFolderAsync(FolderResponseItem? folder)
        {
            if (folder == null) return;
            IsBusy = true;
            string? error = folder.IsLightroom
                ? await _engineClient.ImportLightroomAsync(folder.FolderPath)
                : (await _engineClient.IndexFolderAsync(folder.FolderPath) ? null
                   : "Não foi possível iniciar: já há uma indexação a decorrer, ou o motor não respondeu.");
            IsBusy = false;

            if (error == null)
                System.Windows.MessageBox.Show("Sincronização iniciada. O progresso aparece no rodapé da janela principal.",
                    "Sincronizar", System.Windows.MessageBoxButton.OK, System.Windows.MessageBoxImage.Information);
            else
                System.Windows.MessageBox.Show(error, "Sincronizar", System.Windows.MessageBoxButton.OK,
                    System.Windows.MessageBoxImage.Warning);
        }

        [RelayCommand]
        private async Task DeleteFolderAsync(FolderResponseItem? folder)
        {
            if (folder == null) return;

            var result = System.Windows.MessageBox.Show(
                $"Tem a certeza que deseja eliminar o Índice da pasta:\n{folder.FolderPath}?\n\n(Isto apagará os Vectores da IA e metadados, mas NUNCA as suas fotografias originais).",
                "Aviso de Eliminação",
                System.Windows.MessageBoxButton.YesNo,
                System.Windows.MessageBoxImage.Warning);

            if (result == System.Windows.MessageBoxResult.Yes)
            {
                IsBusy = true;
                bool success = await _engineClient.DeleteFolderAsync(folder.Id);
                if (success)
                {
                    Folders.Remove(folder);
                    System.Windows.MessageBox.Show("Pasta removida com sucesso. Recomenda-se reiniciar uma pesquisa.", "Sucesso", System.Windows.MessageBoxButton.OK, System.Windows.MessageBoxImage.Information);
                }
                else
                {
                    System.Windows.MessageBox.Show("Falha ao eliminar. O motor Python pode estar a processar esta pasta.", "Erro", System.Windows.MessageBoxButton.OK, System.Windows.MessageBoxImage.Error);
                }
                IsBusy = false;
            }
        }
    }
}
