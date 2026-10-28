using FotoAI.Desktop.ViewModels;
using System.Windows;

namespace FotoAI.Desktop.Views
{
    public partial class MainWindow : Window
    {
        public MainWindow(MainWindowViewModel viewModel)
        {
            InitializeComponent();
            DataContext = viewModel;
        }

        private void MenuItemExit_Click(object sender, RoutedEventArgs e)
        {
            Application.Current.Shutdown();
        }
    }
}
