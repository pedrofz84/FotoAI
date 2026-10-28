using System.Text.Json.Serialization;

namespace FotoAI.Desktop.Models
{
    public class EngineStatusModel
    {
        [JsonPropertyName("is_running")]
        public bool IsRunning { get; set; }

        [JsonPropertyName("current_folder")]
        public string CurrentFolder { get; set; } = string.Empty;

        [JsonPropertyName("total_files_found")]
        public int TotalFilesFound { get; set; }

        [JsonPropertyName("files_processed")]
        public int FilesProcessed { get; set; }

        [JsonPropertyName("errors")]
        public int Errors { get; set; }

        /// <summary>SCANNING, DB_SYNC, MODEL, INDEXING, IDLE, FAILED</summary>
        [JsonPropertyName("phase")]
        public string Phase { get; set; } = "IDLE";

        /// <summary>Texto já formatado pelo motor, pronto a mostrar.</summary>
        [JsonPropertyName("message")]
        public string Message { get; set; } = string.Empty;

        /// <summary>0..1, ou negativo quando o progresso é indeterminado.</summary>
        [JsonPropertyName("progress")]
        public double Progress { get; set; } = -1;

        [JsonPropertyName("eta_seconds")]
        public int? EtaSeconds { get; set; }
    }
}
