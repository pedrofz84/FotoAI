using System.Collections.Generic;
using System.Text.Json.Serialization;

namespace FotoAI.Desktop.Models
{
    public class FolderResponseItem
    {
        [JsonPropertyName("id")]
        public int Id { get; set; }
        
        [JsonPropertyName("folder_path")]
        public string FolderPath { get; set; } = string.Empty;
        
        [JsonPropertyName("last_scanned")]
        public string LastScanned { get; set; } = string.Empty;
        
        [JsonPropertyName("scan_status")]
        public string ScanStatus { get; set; } = string.Empty;

        [JsonPropertyName("image_count")]
        public int ImageCount { get; set; }

        [JsonPropertyName("source_type")]
        public string SourceType { get; set; } = "FOLDER";

        [JsonIgnore]
        public bool IsLightroom => SourceType == "LIGHTROOM";

        [JsonIgnore]
        public string TypeLabel => IsLightroom ? "Catálogo Lightroom" : "Pasta";
    }

    public class FolderListResponse
    {
        [JsonPropertyName("folders")]
        public List<FolderResponseItem> Folders { get; set; } = new();
    }
}
