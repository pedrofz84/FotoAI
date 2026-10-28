using FotoAI.Desktop.Models;
using System.Net.Http;
using System.Net.Http.Json;
using System.Threading.Tasks;
using System;
using Microsoft.Extensions.Logging;

namespace FotoAI.Desktop.Services
{
    public class EngineClient
    {
        private readonly HttpClient _httpClient;
        private readonly ILogger<EngineClient> _logger;

        public EngineClient(HttpClient httpClient, ILogger<EngineClient> logger)
        {
            _httpClient = httpClient;
            _logger = logger;
        }

        public async Task<bool> HealthCheckAsync()
        {
            try
            {
                var response = await _httpClient.GetAsync("api/health");
                return response.IsSuccessStatusCode;
            }
            catch
            {
                return false;
            }
        }

        public async Task<bool> IndexFolderAsync(string folderPath)
        {
            try
            {
                var response = await _httpClient.PostAsync($"api/index?folder_path={Uri.EscapeDataString(folderPath)}", null);
                return response.IsSuccessStatusCode;
            }
            catch
            {
                return false;
            }
        }

        /// <summary>
        /// Importa (ou volta a sincronizar) um catálogo do Lightroom. Devolve null se correu bem,
        /// ou a mensagem de erro do motor (ex.: Lightroom aberto).
        /// </summary>
        public async Task<string?> ImportLightroomAsync(string catalogPath)
        {
            try
            {
                var response = await _httpClient.PostAsync($"api/lightroom/import?catalog_path={Uri.EscapeDataString(catalogPath)}", null);
                if (response.IsSuccessStatusCode) return null;
                try
                {
                    var body = await response.Content.ReadFromJsonAsync<EngineMessage>();
                    if (!string.IsNullOrWhiteSpace(body?.Message)) return body!.Message;
                }
                catch { }
                return $"O motor recusou o pedido ({(int)response.StatusCode}).";
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Falha ao pedir a importação do Lightroom.");
                return "O motor de IA não respondeu.";
            }
        }

        private class EngineMessage
        {
            [System.Text.Json.Serialization.JsonPropertyName("message")]
            public string? Message { get; set; }
        }

        public async Task<FolderListResponse?> GetFoldersAsync()
        {
            try
            {
                return await _httpClient.GetFromJsonAsync<FolderListResponse>("api/folders");
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to get folders from Engine.");
                return null;
            }
        }

        public async Task<bool> DeleteFolderAsync(int folderId)
        {
            try
            {
                var response = await _httpClient.DeleteAsync($"api/folders/{folderId}");
                return response.IsSuccessStatusCode;
            }
            catch
            {
                return false;
            }
        }

        public async Task<EngineStatusModel?> GetStatusAsync()
        {
            try
            {
                return await _httpClient.GetFromJsonAsync<EngineStatusModel>("api/status");
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to get status from Engine.");
                return null;
            }
        }

        public async Task<SearchResponseModel?> SearchAsync(string query, int topK = 50)
        {
            try
            {
                var payload = new { query, top_k = topK };
                var response = await _httpClient.PostAsJsonAsync("api/search", payload);
                if (response.IsSuccessStatusCode)
                {
                    return await response.Content.ReadFromJsonAsync<SearchResponseModel>();
                }
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Search failed returning zero results.");
            }
            return null;
        }

        public async Task<SearchResponseModel?> SearchByImageAsync(string filePath, int topK = 50)
        {
            try
            {
                using var content = new MultipartFormDataContent();
                var fileContent = new ByteArrayContent(await System.IO.File.ReadAllBytesAsync(filePath));
                fileContent.Headers.ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue("image/jpeg");
                content.Add(fileContent, "file", System.IO.Path.GetFileName(filePath));

                var response = await _httpClient.PostAsync($"api/search/image?top_k={topK}", content);
                if (response.IsSuccessStatusCode)
                {
                    return await response.Content.ReadFromJsonAsync<SearchResponseModel>();
                }
                else
                {
                    var errorDetail = await response.Content.ReadAsStringAsync();
                    _logger.LogWarning("SearchByImage failed: {Status} - {Detail}", response.StatusCode, errorDetail);
                }
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "SearchByImage failed due to exception.");
            }
            return null;
        }

        public async Task<SearchResponseModel?> SearchSimilarAsync(int photoId, int topK = 50)
        {
            try
            {
                var response = await _httpClient.GetAsync($"api/search/similar/{photoId}?top_k={topK}");
                if (response.IsSuccessStatusCode)
                {
                    return await response.Content.ReadFromJsonAsync<SearchResponseModel>();
                }
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "SearchSimilar (ID: {PhotoId}) failed.", photoId);
            }
            return null;
        }
    }
}
