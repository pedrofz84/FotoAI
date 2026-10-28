using System.Text.Json.Serialization;

namespace FotoAI.Desktop.Models
{
    public class SearchResultModel
    {
        [JsonPropertyName("id")]
        public int Id { get; set; }

        [JsonPropertyName("guid")]
        public string Guid { get; set; } = string.Empty;

        [JsonPropertyName("file_name")]
        public string FileName { get; set; } = string.Empty;

        [JsonPropertyName("file_path")]
        public string FilePath { get; set; } = string.Empty;

        [JsonPropertyName("score")]
        public double Score { get; set; }

        public string ThumbnailUrl => $"http://127.0.0.1:8000/api/photos/{Guid}/thumbnail";
        public string PreviewUrl => $"http://127.0.0.1:8000/api/photos/{Guid}/preview";
    }

    public class SearchResponseModel
    {
        [JsonPropertyName("results")]
        public SearchResultModel[] Results { get; set; } = [];
    }
}
