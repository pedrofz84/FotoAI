using FotoAI.Desktop.Services;
using FotoAI.Desktop.ViewModels;
using FotoAI.Desktop.Views;
using Microsoft.Extensions.DependencyInjection;
using System;
using System.IO;
using System.Windows;
using Serilog;

namespace FotoAI.Desktop
{
    public partial class App : Application
    {
        public new static App Current => (App)Application.Current;
        public IServiceProvider Services { get; }

        public App()
        {
            string localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            string logDir = Path.Combine(localAppData, "FotoAI", "Logs");
            string logFile = Path.Combine(logDir, "Desktop_.log");

            Log.Logger = new LoggerConfiguration()
                .MinimumLevel.Debug()
                .WriteTo.Debug()
                .WriteTo.File(logFile, rollingInterval: RollingInterval.Day, retainedFileCountLimit: 7)
                .CreateLogger();

            Log.Information("Iniciando FotoAI.Desktop...");

            Services = ConfigureServices();
        }

        private static IServiceProvider ConfigureServices()
        {
            var services = new ServiceCollection();

            services.AddLogging(loggingBuilder => loggingBuilder.AddSerilog(dispose: true));

            services.AddSingleton<PythonEngineRunner>();
            services.AddHttpClient<EngineClient>(client =>
            {
                client.BaseAddress = new Uri("http://127.0.0.1:8000/");
                client.Timeout = TimeSpan.FromSeconds(30);
            });

            // ViewModels
            services.AddTransient<MainWindowViewModel>();
            services.AddTransient<ManageFoldersViewModel>();

            // Views
            services.AddTransient<MainWindow>();
            services.AddTransient<ManageFoldersWindow>();
            services.AddTransient<AboutWindow>();

            return services.BuildServiceProvider();
        }

        private PythonEngineRunner? _engineRunner;

        protected override void OnStartup(StartupEventArgs e)
        {
            base.OnStartup(e);
            
            _engineRunner = Services.GetRequiredService<PythonEngineRunner>();
            _engineRunner.StartEngine();

            var mainWindow = Services.GetRequiredService<MainWindow>();
            mainWindow.Show();
        }

        protected override void OnExit(ExitEventArgs e)
        {
            _engineRunner?.Dispose();
            Log.Information("A encerrar FotoAI.Desktop...");
            Log.CloseAndFlush();
            base.OnExit(e);
        }
    }
}
