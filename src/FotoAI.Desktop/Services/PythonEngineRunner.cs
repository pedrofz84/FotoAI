using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using Microsoft.Extensions.Logging;

namespace FotoAI.Desktop.Services
{
    public class PythonEngineRunner : IDisposable
    {
        private readonly ILogger<PythonEngineRunner> _logger;
        private Process? _engineProcess;
        private IntPtr _jobHandle;

        /// <summary>True se o processo Python terminou (normalmente por erro no arranque).</summary>
        public bool HasExited
        {
            get
            {
                try { return _engineProcess == null || _engineProcess.HasExited; }
                catch (InvalidOperationException) { return true; } // processo já libertado ao fechar a app
            }
        }

        /// <summary>Última linha de erro do Python (ex: ModuleNotFoundError), para mostrar na UI.</summary>
        public string? LastErrorLine { get; private set; }

        /// <summary>Falha ao lançar o processo (ex: Python não encontrado).</summary>
        public string? StartFailure { get; private set; }

        public PythonEngineRunner(ILogger<PythonEngineRunner> logger)
        {
            _logger = logger;
        }

        public void StartEngine()
        {
            // Resolução agnóstica Prod vs Dev
            string basePath = AppDomain.CurrentDomain.BaseDirectory;
            string enginePath = Path.Combine(basePath, "Engine"); // Alvo de Produção InnoSetup

            if (!Directory.Exists(enginePath))
            {
                // Fallback para Ambiente de Desenvolvimento (dotnet run)
                DirectoryInfo? dir = new DirectoryInfo(basePath);
                while (dir != null && dir.Name != "src" && dir.Name != "FotosAI")
                {
                    dir = dir.Parent;
                }
                
                if (dir != null && dir.Name == "src")
                    enginePath = Path.Combine(dir.FullName, "FotoAI.Engine");
                else if (dir != null && dir.Name == "FotosAI")
                    enginePath = Path.Combine(dir.FullName, "src", "FotoAI.Engine");
                else
                    enginePath = Path.GetFullPath(Path.Combine(basePath, @"..\..\..\..\FotoAI.Engine"));
            }
            
            string pythonExe = ResolvePython(enginePath);
            _logger.LogInformation("A usar Python: {Python}", pythonExe);

            var startInfo = new ProcessStartInfo
            {
                FileName = pythonExe,
                Arguments = "main.py",
                WorkingDirectory = enginePath,
                UseShellExecute = false,
                CreateNoWindow = true, // Impede a abertura da Consola preta no ecrã
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                StandardOutputEncoding = System.Text.Encoding.UTF8,
                StandardErrorEncoding = System.Text.Encoding.UTF8
            };
            // Acentos corretos nos logs do Python
            startInfo.Environment["PYTHONIOENCODING"] = "utf-8";
            startInfo.Environment["PYTHONUTF8"] = "1";

            try
            {
                _engineProcess = Process.Start(startInfo);
                if (_engineProcess != null)
                {
                    AssignProcessToJobObject(_engineProcess);
                    
                    _engineProcess.OutputDataReceived += (s, e) =>
                    {
                        if (!string.IsNullOrWhiteSpace(e.Data))
                            _logger.LogInformation("[Python] {Output}", e.Data);
                    };

                    _engineProcess.ErrorDataReceived += (s, e) =>
                    {
                        if (string.IsNullOrWhiteSpace(e.Data)) return;
                        // O loguru escreve tudo para stderr; só as linhas de erro reais ficam como erro
                        bool isError = e.Data.Contains("Error") || e.Data.Contains("Exception")
                                       || e.Data.Contains("| ERROR") || e.Data.Contains("| CRITICAL");
                        if (isError)
                        {
                            LastErrorLine = e.Data.Trim();
                            _logger.LogError("[Python] {Error}", e.Data);
                        }
                        else
                        {
                            _logger.LogInformation("[Python] {Output}", e.Data);
                        }
                    };

                    _engineProcess.BeginOutputReadLine();
                    _engineProcess.BeginErrorReadLine();
                    
                    _logger.LogInformation("Processo Python iniciado e pipes registadas.");
                }
            }
            catch (Exception ex)
            {
                StartFailure = $"Não foi possível lançar o Python ({pythonExe}): {ex.Message}";
                _logger.LogCritical(ex, "[FALHA GRAVE] Impossível arrancar o motor Python");
            }
        }

        /// <summary>
        /// Ordem: variável FOTOAI_PYTHON, venv dentro do motor (.venv ou venv),
        /// venv na raiz do repositório e, por fim, o python do PATH.
        /// </summary>
        private static string ResolvePython(string enginePath)
        {
            string? fromEnv = Environment.GetEnvironmentVariable("FOTOAI_PYTHON");
            if (!string.IsNullOrWhiteSpace(fromEnv) && File.Exists(fromEnv))
                return fromEnv;

            var candidates = new[]
            {
                Path.Combine(enginePath, ".venv", "Scripts", "python.exe"),
                Path.Combine(enginePath, "venv", "Scripts", "python.exe"),
                Path.GetFullPath(Path.Combine(enginePath, "..", "..", ".venv", "Scripts", "python.exe")),
            };
            foreach (var c in candidates)
            {
                if (File.Exists(c)) return c;
            }
            return "python";
        }

        private void AssignProcessToJobObject(Process process)
        {
            _jobHandle = CreateJobObject(IntPtr.Zero, null);
            var info = new JOBOBJECT_BASIC_LIMIT_INFORMATION
            {
                LimitFlags = 0x2000 // JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (Garante aniquilação automática do processo Python se o WPF for fechado violentamente pelo Task Manager)
            };

            var extendedInfo = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION
            {
                BasicLimitInformation = info
            };

            int length = Marshal.SizeOf(typeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION));
            IntPtr extendedInfoPtr = Marshal.AllocHGlobal(length);
            Marshal.StructureToPtr(extendedInfo, extendedInfoPtr, false);

            if (!SetInformationJobObject(_jobHandle, 9, extendedInfoPtr, (uint)length))
            {
                _logger.LogWarning("Erro Kernel32: Incapaz de ligar Memory Limit a JobObject.");
            }

            AssignProcessToJobObject(_jobHandle, process.Handle);
            Marshal.FreeHGlobal(extendedInfoPtr);
        }

        public void Dispose()
        {
            if (_engineProcess != null && !_engineProcess.HasExited)
            {
                _engineProcess.Kill();
                _engineProcess.Dispose();
            }
        }

        // P/Invoke Kernel32
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
        static extern IntPtr CreateJobObject(IntPtr a, string? lpName);

        [DllImport("kernel32.dll")]
        static extern bool SetInformationJobObject(IntPtr hJob, int infoClass, IntPtr lpJobObjectInfo, uint cbJobObjectInfoLength);

        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);

        [StructLayout(LayoutKind.Sequential)]
        struct JOBOBJECT_BASIC_LIMIT_INFORMATION
        {
            public Int64 PerProcessUserTimeLimit;
            public Int64 PerJobUserTimeLimit;
            public UInt32 LimitFlags;
            public UIntPtr MinimumWorkingSetSize;
            public UIntPtr MaximumWorkingSetSize;
            public UInt32 ActiveProcessLimit;
            public Int64 Affinity;
            public UInt32 PriorityClass;
            public UInt32 SchedulingClass;
        }

        [StructLayout(LayoutKind.Sequential)]
        struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION
        {
            public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
            public UIntPtr IoInfo_ReadOperationCount;
            public UIntPtr IoInfo_WriteOperationCount;
            public UIntPtr IoInfo_OtherOperationCount;
            public UIntPtr IoInfo_ReadTransferCount;
            public UIntPtr IoInfo_WriteTransferCount;
            public UIntPtr IoInfo_OtherTransferCount;
            public UIntPtr ProcessMemoryLimit;
            public UIntPtr JobMemoryLimit;
            public UIntPtr PeakProcessMemoryUsed;
            public UIntPtr PeakJobMemoryUsed;
        }
    }
}
