using FotoAI.Desktop.ViewModels;
using System.Windows;

namespace FotoAI.Desktop.Views
{
    public partial class ManageFoldersWindow : Window
    {
        private readonly ManageFoldersViewModel _viewModel;

        public ManageFoldersWindow(ManageFoldersViewModel viewModel)
        {
            InitializeComponent();
            _viewModel = viewModel;
            DataContext = _viewModel;
            
            Loaded += async (s, e) => await _viewModel.LoadFoldersAsync();
        }
    }
}
