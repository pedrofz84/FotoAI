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

        [JsonPropertyName("capture_date")]
        public string? CaptureDate { get; set; }

        /// <summary>Data à portuguesa (dd/mm/aaaa), ou vazio se a foto não tiver data.</summary>
        public string CaptureDateText =>
            System.DateTime.TryParse(CaptureDate, out var d) ? d.ToString("dd/MM/yyyy") : "";

        public string ThumbnailUrl => $"http://127.0.0.1:8000/api/photos/{Guid}/thumbnail";
        public string PreviewUrl => $"http://127.0.0.1:8000/api/photos/{Guid}/preview";
    }

    public class YearCountModel
    {
        [JsonPropertyName("year")]
        public int Year { get; set; }

        [JsonPropertyName("count")]
        public int Count { get; set; }
    }

    public class YearsResponseModel
    {
        [JsonPropertyName("years")]
        public YearCountModel[] Years { get; set; } = [];

        [JsonPropertyName("without_date")]
        public int WithoutDate { get; set; }
    }

    public class SearchResponseModel
    {
        [JsonPropertyName("results")]
        public SearchResultModel[] Results { get; set; } = [];

        [JsonPropertyName("has_more")]
        public bool HasMore { get; set; }
    }
}
