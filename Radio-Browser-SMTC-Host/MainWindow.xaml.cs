using System.Net;
using System.Net.Http;
using System.IO;
using System.Text.RegularExpressions;
using System.Text;
using System.Text.Json;
using System.Linq;
using System.Windows;
using Windows.Media;
using Windows.Media.Core;
using Windows.Media.Playback;
using Windows.Foundation.Collections;
using Windows.Storage.Streams;

namespace RadioBrowserSmtcHost;

public partial class MainWindow : Window
{
    private readonly string _listenPrefix =
        Environment.GetEnvironmentVariable("RADIO_SMTC_HOST_PREFIX")
        ?? "http://127.0.0.1:8765/";
    private HttpListener? _listener;
    private CancellationTokenSource? _cts;
    private Task? _listenerTask;
    private MediaPlayer? _mediaPlayer;
    private MediaPlaybackItem? _currentPlaybackItem;
    private SystemMediaTransportControls? _smtc;
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true,
    };
    private string _lastTitle = "Radio Stream";
    private string _lastArtist = "Radio Browser";
    private string _lastStation = "Radio Browser";
    private string _lastStatus = "Stopped";
    private string? _lastError;
    private string? _lastUrl;
    private double _lastVolume = 100.0;
    private DateTimeOffset? _lastUpdatedAt;
    private readonly HashSet<TimedMetadataTrack> _attachedTimedTracks = [];
    private CancellationTokenSource? _icyMetadataCts;
    private Task? _icyMetadataTask;
    private CancellationTokenSource? _playStartupCts;
    private static readonly TimeSpan PlayStartupTimeout = TimeSpan.FromSeconds(12);
    private readonly HttpClient _icyHttpClient = new(
        new HttpClientHandler
        {
            AutomaticDecompression = DecompressionMethods.GZip | DecompressionMethods.Deflate,
        }
    );
    private static readonly Regex StreamTitleRegex = new(
        "StreamTitle='(?<title>.*?)';?",
        RegexOptions.IgnoreCase | RegexOptions.Compiled
    );
    private static readonly UTF8Encoding Utf8Strict = new(false, true);
    private readonly Encoding? _defaultStreamEncoding;

    public MainWindow()
    {
        Encoding.RegisterProvider(CodePagesEncodingProvider.Instance);
        _defaultStreamEncoding = ResolveDefaultStreamEncoding();
        InitializeComponent();
        SourceInitialized += OnSourceInitialized;
        Loaded += OnLoaded;
        Closing += OnClosing;
    }

    private void OnSourceInitialized(object? sender, EventArgs e)
    {
        try
        {
            _mediaPlayer = new MediaPlayer
            {
                AutoPlay = false,
                Volume = 1.0,
            };
            _mediaPlayer.CommandManager.IsEnabled = true;
            _mediaPlayer.MediaOpened += MediaPlayer_MediaOpened;
            _mediaPlayer.MediaFailed += MediaPlayer_MediaFailed;
            _mediaPlayer.PlaybackSession.PlaybackStateChanged += PlaybackSession_PlaybackStateChanged;
            _smtc = _mediaPlayer.SystemMediaTransportControls;
            _smtc.IsEnabled = true;
            _smtc.IsPlayEnabled = true;
            _smtc.IsPauseEnabled = true;
            _smtc.IsNextEnabled = false;
            _smtc.IsPreviousEnabled = false;
            SetMedia("Radio Browser", "SMTC Host", MediaPlaybackStatus.Stopped);
            _lastStatus = ToLogicalStatus(MediaPlaybackStatus.Stopped);
            UpdateNowPlayingUi(_lastArtist, _lastTitle);
        }
        catch (Exception ex)
        {
            StateText.Text = $"SMTC init error: {ex.Message}";
        }
    }

    private void OnLoaded(object sender, RoutedEventArgs e)
    {
        EndpointText.Text = $"Listening: {_listenPrefix} (smtc + player API)";
        _cts = new CancellationTokenSource();
        _listener = new HttpListener();
        _listener.Prefixes.Add(_listenPrefix);
        _listener.Start();
        _listenerTask = Task.Run(() => ListenLoopAsync(_cts.Token));
    }

    private void OnClosing(object? sender, System.ComponentModel.CancelEventArgs e)
    {
        try
        {
            _cts?.Cancel();
            if (_listener?.IsListening == true)
            {
                _listener.Stop();
            }
            _listener?.Close();
            _mediaPlayer?.Pause();
            if (_mediaPlayer is not null)
            {
                _mediaPlayer.MediaOpened -= MediaPlayer_MediaOpened;
                _mediaPlayer.MediaFailed -= MediaPlayer_MediaFailed;
                _mediaPlayer.PlaybackSession.PlaybackStateChanged -= PlaybackSession_PlaybackStateChanged;
            }
            _mediaPlayer?.Dispose();
            _mediaPlayer = null;
            CancelPlayStartupTimeout();
            StopIcyMetadataMonitor();
            _icyHttpClient.Dispose();
            DetachTimedMetadataHandlers();
        }
        catch
        {
            // Ignore shutdown errors.
        }
    }

    private async Task ListenLoopAsync(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested && _listener is not null && _listener.IsListening)
        {
            HttpListenerContext? context = null;
            try
            {
                context = await _listener.GetContextAsync();
            }
            catch
            {
                if (ct.IsCancellationRequested)
                {
                    break;
                }
            }

            if (context is null)
            {
                continue;
            }

            _ = Task.Run(() => HandleRequestAsync(context, ct), ct);
        }
    }

    private async Task HandleRequestAsync(HttpListenerContext context, CancellationToken ct)
    {
        var req = context.Request;
        var res = context.Response;
        res.ContentType = "application/json; charset=utf-8";

        try
        {
            if (req.HttpMethod == "GET" && req.Url?.AbsolutePath == "/health")
            {
                await WriteJsonAsync(res, 200, "{\"success\":true,\"service\":\"smtc-host\"}");
                return;
            }

            if (req.HttpMethod == "GET" && req.Url?.AbsolutePath == "/debug/state")
            {
                var debug = new
                {
                    success = true,
                    state = new
                    {
                        title = _lastTitle,
                        artist = _lastArtist,
                        status = _lastStatus,
                        error = _lastError,
                        updated_at = _lastUpdatedAt?.ToString("O"),
                    },
                };
                await WriteJsonAsync(res, 200, JsonSerializer.Serialize(debug));
                return;
            }

            if (req.HttpMethod == "POST" && req.Url?.AbsolutePath == "/smtc/update")
            {
                using var reader = new StreamReader(req.InputStream, req.ContentEncoding);
                var body = await reader.ReadToEndAsync(ct);
                var payload = JsonSerializer.Deserialize<SmtcUpdateRequest>(
                    body,
                    JsonOptions
                );
                if (payload is null)
                {
                    await WriteJsonAsync(res, 400, "{\"success\":false,\"error\":\"Invalid JSON\"}");
                    return;
                }

                await Dispatcher.InvokeAsync(() =>
                {
                    var status = ParseStatus(payload.Status);
                    var title = string.IsNullOrWhiteSpace(payload.Title)
                        ? "Radio Stream"
                        : payload.Title.Trim();
                    var artist = string.IsNullOrWhiteSpace(payload.Artist)
                        ? "Radio Browser"
                        : payload.Artist.Trim();
                    SetMedia(title, artist, status);
                    _lastTitle = title;
                    _lastArtist = artist;
                    _lastStatus = ToLogicalStatus(status);
                    _lastUpdatedAt = DateTimeOffset.UtcNow;
                    StateText.Text = $"Status: {ToUiStatus(status)}";
                    UpdateNowPlayingUi(artist, title);
                });

                await WriteJsonAsync(res, 200, "{\"success\":true}");
                return;
            }

            if (req.HttpMethod == "POST" && req.Url?.AbsolutePath == "/player/play")
            {
                using var reader = new StreamReader(req.InputStream, req.ContentEncoding);
                var body = await reader.ReadToEndAsync(ct);
                var payload = JsonSerializer.Deserialize<PlayerPlayRequest>(body, JsonOptions);
                if (payload is null || string.IsNullOrWhiteSpace(payload.Url))
                {
                    await WriteJsonAsync(res, 400, "{\"success\":false,\"error\":\"Missing url\"}");
                    return;
                }

                var result = await Dispatcher.InvokeAsync(() =>
                    TryPlayStream(payload.Url.Trim(), payload.Name?.Trim() ?? "")
                );
                await WriteJsonAsync(res, result.Success ? 200 : 500, result.Json);
                return;
            }

            if (req.HttpMethod == "POST" && req.Url?.AbsolutePath == "/player/stop")
            {
                var result = await Dispatcher.InvokeAsync(TryStopStream);
                await WriteJsonAsync(res, result.Success ? 200 : 500, result.Json);
                return;
            }

            if (req.HttpMethod == "POST" && req.Url?.AbsolutePath == "/player/volume")
            {
                using var reader = new StreamReader(req.InputStream, req.ContentEncoding);
                var body = await reader.ReadToEndAsync(ct);
                var payload = JsonSerializer.Deserialize<PlayerVolumeRequest>(body, JsonOptions);
                if (payload is null)
                {
                    await WriteJsonAsync(res, 400, "{\"success\":false,\"error\":\"Invalid JSON\"}");
                    return;
                }

                var result = await Dispatcher.InvokeAsync(() =>
                    TrySetVolume(payload.Volume)
                );
                await WriteJsonAsync(res, result.Success ? 200 : 500, result.Json);
                return;
            }

            if (req.HttpMethod == "GET" && req.Url?.AbsolutePath == "/player/status")
            {
                var statusJson = await Dispatcher.InvokeAsync(GetPlayerStatusJson);
                await WriteJsonAsync(res, 200, statusJson);
                return;
            }

            await WriteJsonAsync(res, 404, "{\"success\":false,\"error\":\"Not found\"}");
        }
        catch (Exception ex)
        {
            await Dispatcher.InvokeAsync(() => { StateText.Text = $"Request error: {ex.Message}"; });
            await WriteJsonAsync(res, 500, "{\"success\":false,\"error\":\"Internal error\"}");
        }
    }

    private static async Task WriteJsonAsync(HttpListenerResponse response, int statusCode, string body)
    {
        var bytes = Encoding.UTF8.GetBytes(body);
        response.StatusCode = statusCode;
        response.ContentLength64 = bytes.Length;
        await response.OutputStream.WriteAsync(bytes, 0, bytes.Length);
        response.Close();
    }

    private void SetMedia(string title, string artist, MediaPlaybackStatus status)
    {
        if (_smtc is null)
        {
            return;
        }

        var displayArtist = GetStationForFlyout();
        var displayTitle = FormatTitleForFlyout(artist, title);

        if (_currentPlaybackItem is not null)
        {
            var props = _currentPlaybackItem.GetDisplayProperties();
            props.Type = MediaPlaybackType.Music;
            props.MusicProperties.Title = displayTitle;
            props.MusicProperties.Artist = displayArtist;
            props.MusicProperties.AlbumTitle = artist;
            _currentPlaybackItem.ApplyDisplayProperties(props);
        }

        var updater = _smtc.DisplayUpdater;
        updater.AppMediaId = "Radio Browser";
        updater.Type = MediaPlaybackType.Music;
        updater.MusicProperties.Title = displayTitle;
        updater.MusicProperties.Artist = displayArtist;
        updater.MusicProperties.AlbumTitle = artist;
        updater.Update();
        _smtc.PlaybackStatus = status;
    }

    private string GetStationForFlyout()
    {
        return string.IsNullOrWhiteSpace(_lastStation) ? "Radio Browser" : _lastStation.Trim();
    }

    private static string FormatTitleForFlyout(string artist, string title)
    {
        var a = string.IsNullOrWhiteSpace(artist) ? "" : artist.Trim();
        var t = string.IsNullOrWhiteSpace(title) ? "Radio Stream" : title.Trim();
        if (string.IsNullOrWhiteSpace(a))
        {
            return t;
        }
        if (a.Equals(t, StringComparison.OrdinalIgnoreCase))
        {
            return t;
        }
        return $"{a} - {t}";
    }

    private void UpdateNowPlayingUi(string artist, string title)
    {
        var station = GetStationForFlyout();
        var stationText = HasResolvedStation(station) ? station : "—";
        var hasTrackMetadata = HasResolvedTrackMetadata(artist, title, station);
        var artistText = hasTrackMetadata ? artist : "—";
        var titleText = hasTrackMetadata ? title : "—";

        StationText.Text = $"Station: {stationText}";
        ArtistText.Text = $"Artist: {artistText}";
        TitleText.Text = $"Title: {titleText}";
    }

    private bool HasResolvedStation(string station)
    {
        if (string.IsNullOrWhiteSpace(station))
        {
            return false;
        }

        if (string.IsNullOrWhiteSpace(_lastUrl))
        {
            return false;
        }

        if (station.Equals("Radio Browser", StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }

        return true;
    }

    private static bool HasResolvedTrackMetadata(string artist, string title, string station)
    {
        var a = (artist ?? "").Trim();
        var t = (title ?? "").Trim();
        var s = (station ?? "").Trim();

        if (string.IsNullOrWhiteSpace(a) || string.IsNullOrWhiteSpace(t))
        {
            return false;
        }

        if (t.Equals("Radio Stream", StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }

        if (!string.IsNullOrWhiteSpace(s))
        {
            if (a.Equals(s, StringComparison.OrdinalIgnoreCase))
            {
                return false;
            }

            if (t.Equals(s, StringComparison.OrdinalIgnoreCase))
            {
                return false;
            }
        }

        return true;
    }

    private static MediaPlaybackStatus ParseStatus(string? status)
    {
        return status?.Trim().ToLowerInvariant() switch
        {
            "playing" => MediaPlaybackStatus.Playing,
            "paused" => MediaPlaybackStatus.Paused,
            "stopped" => MediaPlaybackStatus.Stopped,
            "changing" => MediaPlaybackStatus.Changing,
            "connecting" => MediaPlaybackStatus.Changing,
            _ => MediaPlaybackStatus.Changing,
        };
    }

    private sealed class SmtcUpdateRequest
    {
        public string? Title { get; set; }
        public string? Artist { get; set; }
        public string? Status { get; set; }
    }

    private sealed class PlayerPlayRequest
    {
        public string? Url { get; set; }
        public string? Name { get; set; }
    }

    private sealed class PlayerVolumeRequest
    {
        public int Volume { get; set; }
    }

    private sealed class OpResult
    {
        public bool Success { get; set; }
        public string Json { get; set; } = "{}";
    }

    private OpResult TryPlayStream(string url, string name)
    {
        if (_mediaPlayer is null)
        {
            return new OpResult { Success = false, Json = "{\"success\":false,\"error\":\"MediaPlayer not initialized\"}" };
        }

        try
        {
            var source = MediaSource.CreateFromUri(new Uri(url));
            var title = string.IsNullOrWhiteSpace(name) ? "Radio Stream" : name;
            var artist = string.IsNullOrWhiteSpace(name) ? "Radio Browser" : name;
            _lastStation = string.IsNullOrWhiteSpace(name) ? "Radio Browser" : name.Trim();

            // For MediaPlayer-backed sessions, Windows UI prefers metadata from
            // MediaPlaybackItem display properties over raw SMTC updater fields.
            var item = new MediaPlaybackItem(source);
            var props = item.GetDisplayProperties();
            props.Type = MediaPlaybackType.Music;
            props.MusicProperties.Title = title;
            props.MusicProperties.Artist = artist;
            item.ApplyDisplayProperties(props);

            DetachTimedMetadataHandlers();
            _currentPlaybackItem = item;
            AttachTimedMetadataHandlers(item);

            _mediaPlayer.Source = item;
            _lastError = null;
            _mediaPlayer.Play();
            StartIcyMetadataMonitor(url);
            SetMedia(title, artist, MediaPlaybackStatus.Changing);
            _lastUrl = url;
            _lastTitle = title;
            _lastArtist = artist;
            _lastStatus = "Connecting";
            _lastUpdatedAt = DateTimeOffset.UtcNow;
            StateText.Text = $"Status: {ToUiStatus(_lastStatus)}";
            UpdateNowPlayingUi(artist, title);
            StartPlayStartupTimeout(url);

            return new OpResult
            {
                Success = true,
                Json = "{\"success\":true}",
            };
        }
        catch (Exception ex)
        {
            return new OpResult
            {
                Success = false,
                Json = JsonSerializer.Serialize(new { success = false, error = ex.Message }),
            };
        }
    }

    private OpResult TryStopStream()
    {
        if (_mediaPlayer is null)
        {
            return new OpResult { Success = false, Json = "{\"success\":false,\"error\":\"MediaPlayer not initialized\"}" };
        }

        try
        {
            _mediaPlayer.Pause();
            _mediaPlayer.Source = null;
            CancelPlayStartupTimeout();
            StopIcyMetadataMonitor();
            DetachTimedMetadataHandlers();
            _lastUrl = null;
            _lastError = null;
            _lastStation = "Radio Browser";
            _lastArtist = "Radio Browser";
            _lastTitle = "Radio Stream";
            SetMedia(_lastTitle, _lastArtist, MediaPlaybackStatus.Stopped);
            _lastStatus = ToLogicalStatus(MediaPlaybackStatus.Stopped);
            _lastUpdatedAt = DateTimeOffset.UtcNow;
            StateText.Text = $"Status: {ToUiStatus(MediaPlaybackStatus.Stopped)}";
            UpdateNowPlayingUi(_lastArtist, _lastTitle);
            return new OpResult { Success = true, Json = "{\"success\":true}" };
        }
        catch (Exception ex)
        {
            return new OpResult
            {
                Success = false,
                Json = JsonSerializer.Serialize(new { success = false, error = ex.Message }),
            };
        }
    }

    private OpResult TrySetVolume(int volume)
    {
        if (_mediaPlayer is null)
        {
            return new OpResult { Success = false, Json = "{\"success\":false,\"error\":\"MediaPlayer not initialized\"}" };
        }

        try
        {
            var clamped = Math.Max(0, Math.Min(100, volume));
            _mediaPlayer.Volume = clamped / 100.0;
            _lastVolume = clamped;
            return new OpResult
            {
                Success = true,
                Json = JsonSerializer.Serialize(new { success = true, volume = clamped }),
            };
        }
        catch (Exception ex)
        {
            return new OpResult
            {
                Success = false,
                Json = JsonSerializer.Serialize(new { success = false, error = ex.Message }),
            };
        }
    }

    private string GetPlayerStatusJson()
    {
        if (_mediaPlayer is null)
        {
            return "{\"success\":false,\"error\":\"MediaPlayer not initialized\"}";
        }

        var playbackState = _mediaPlayer.PlaybackSession.PlaybackState;
        var mapped = ToLogicalStatus(playbackState);

        var result = new
        {
            success = true,
            state = mapped,
            playback_state = playbackState.ToString(),
            url = _lastUrl,
            title = _lastTitle,
            artist = _lastArtist,
            error = _lastError,
            volume = (int)Math.Round(_mediaPlayer.Volume * 100.0),
            updated_at = _lastUpdatedAt?.ToString("O"),
        };
        return JsonSerializer.Serialize(result);
    }

    private void MediaPlayer_MediaOpened(MediaPlayer sender, object args)
    {
        _ = Dispatcher.InvokeAsync(() =>
        {
            CancelPlayStartupTimeout();
            _lastError = null;
            var status = ResolveSmtcStatusForMetadataUpdate();
            SetMedia(_lastTitle, _lastArtist, status);
            _lastStatus = GetCurrentLogicalStatus();
            _lastUpdatedAt = DateTimeOffset.UtcNow;
            StateText.Text = $"Status: {ToUiStatus(_lastStatus)}";
        });
    }

    private void MediaPlayer_MediaFailed(MediaPlayer sender, MediaPlayerFailedEventArgs args)
    {
        _ = Dispatcher.InvokeAsync(() =>
        {
            CancelPlayStartupTimeout();
            StopIcyMetadataMonitor();
            var errorText = string.IsNullOrWhiteSpace(args.ErrorMessage)
                ? $"Playback failed ({args.Error})"
                : $"Playback failed: {args.ErrorMessage}";
            _lastError = errorText;
            _lastStatus = ToLogicalStatus(MediaPlaybackStatus.Stopped);
            _lastUpdatedAt = DateTimeOffset.UtcNow;
            SetMedia(_lastTitle, _lastArtist, MediaPlaybackStatus.Stopped);
            StateText.Text = $"Error: {errorText}";
        });
    }

    private void PlaybackSession_PlaybackStateChanged(MediaPlaybackSession sender, object args)
    {
        _ = Dispatcher.InvokeAsync(() =>
        {
            if (string.IsNullOrWhiteSpace(_lastUrl))
            {
                return;
            }

            var status = GetCurrentMediaPlaybackStatus();
            _lastStatus = GetCurrentLogicalStatus();
            _lastUpdatedAt = DateTimeOffset.UtcNow;
            SetMedia(_lastTitle, _lastArtist, status);
            if (string.IsNullOrWhiteSpace(_lastError))
            {
                StateText.Text = $"Status: {ToUiStatus(_lastStatus)}";
            }
        });
    }

    private void StartPlayStartupTimeout(string url)
    {
        CancelPlayStartupTimeout();
        _playStartupCts = new CancellationTokenSource();
        var token = _playStartupCts.Token;

        _ = Task.Run(async () =>
        {
            try
            {
                await Task.Delay(PlayStartupTimeout, token);
            }
            catch (OperationCanceledException)
            {
                return;
            }

            await Dispatcher.InvokeAsync(() =>
            {
                if (token.IsCancellationRequested)
                {
                    return;
                }

                if (!string.Equals(_lastUrl, url, StringComparison.OrdinalIgnoreCase))
                {
                    return;
                }

                var status = GetCurrentMediaPlaybackStatus();
                if (status == MediaPlaybackStatus.Playing)
                {
                    return;
                }

                _lastError = $"Stream start timeout after {(int)PlayStartupTimeout.TotalSeconds}s";
                _lastStatus = ToLogicalStatus(MediaPlaybackStatus.Stopped);
                _lastUpdatedAt = DateTimeOffset.UtcNow;
                SetMedia(_lastTitle, _lastArtist, MediaPlaybackStatus.Stopped);
                StateText.Text = $"Error: {_lastError}";
            });
        }, token);
    }

    private void CancelPlayStartupTimeout()
    {
        try
        {
            _playStartupCts?.Cancel();
        }
        catch
        {
            // Ignore cancellation errors.
        }
        finally
        {
            _playStartupCts?.Dispose();
            _playStartupCts = null;
        }
    }

    private void AttachTimedMetadataHandlers(MediaPlaybackItem item)
    {
        item.TimedMetadataTracksChanged += MediaPlaybackItem_TimedMetadataTracksChanged;
        HookTimedMetadataTracks(item);
    }

    private void DetachTimedMetadataHandlers()
    {
        if (_currentPlaybackItem is not null)
        {
            _currentPlaybackItem.TimedMetadataTracksChanged -= MediaPlaybackItem_TimedMetadataTracksChanged;
        }
        foreach (var track in _attachedTimedTracks)
        {
            track.CueEntered -= TimedMetadataTrack_CueEntered;
        }
        _attachedTimedTracks.Clear();
        _currentPlaybackItem = null;
    }

    private void MediaPlaybackItem_TimedMetadataTracksChanged(
        MediaPlaybackItem sender,
        IVectorChangedEventArgs args
    )
    {
        HookTimedMetadataTracks(sender);
    }

    private void HookTimedMetadataTracks(MediaPlaybackItem item)
    {
        for (var i = 0; i < item.TimedMetadataTracks.Count; i++)
        {
            var track = item.TimedMetadataTracks[i];
            if (_attachedTimedTracks.Add(track))
            {
                item.TimedMetadataTracks.SetPresentationMode(
                    (uint)i,
                    TimedMetadataTrackPresentationMode.ApplicationPresented
                );
                track.CueEntered += TimedMetadataTrack_CueEntered;
            }
        }
    }

    private async void TimedMetadataTrack_CueEntered(TimedMetadataTrack sender, MediaCueEventArgs args)
    {
        var nowPlaying = ExtractNowPlaying(args.Cue);
        if (string.IsNullOrWhiteSpace(nowPlaying))
        {
            return;
        }

        await Dispatcher.InvokeAsync(() =>
        {
            var (artist, title) = ParseArtistAndTitle(nowPlaying, _lastArtist);
            var smtcStatus = ResolveSmtcStatusForMetadataUpdate();
            SetMedia(title, artist, smtcStatus);
            _lastTitle = title;
            _lastArtist = artist;
            _lastStatus = GetCurrentLogicalStatus();
            _lastUpdatedAt = DateTimeOffset.UtcNow;
            StateText.Text = $"Status: {ToUiStatus(_lastStatus)}";
            UpdateNowPlayingUi(artist, title);
        });
    }

    private string ExtractNowPlaying(IMediaCue cue)
    {
        if (cue is DataCue dataCue && dataCue.Data is not null)
        {
            var raw = BufferToString(dataCue.Data);
            if (string.IsNullOrWhiteSpace(raw))
            {
                return string.Empty;
            }

            var streamTitleMatch = StreamTitleRegex.Match(raw);
            if (streamTitleMatch.Success)
            {
                return streamTitleMatch.Groups["title"].Value.Trim();
            }

            return raw.Trim();
        }

        return string.Empty;
    }

    private string BufferToString(IBuffer buffer)
    {
        var reader = DataReader.FromBuffer(buffer);
        var bytes = new byte[buffer.Length];
        reader.ReadBytes(bytes);
        return DecodeIcyTitleBytes(bytes, _defaultStreamEncoding);
    }

    private static (string Artist, string Title) ParseArtistAndTitle(
        string nowPlaying,
        string fallbackArtist
    )
    {
        var value = TryRepairUtf8Mojibake(nowPlaying.Trim());
        var separatorIndex = value.IndexOf(" - ", StringComparison.Ordinal);
        if (separatorIndex <= 0)
        {
            return (TryRepairUtf8Mojibake(fallbackArtist), value);
        }

        var artist = TryRepairUtf8Mojibake(value[..separatorIndex].Trim());
        var title = TryRepairUtf8Mojibake(value[(separatorIndex + 3)..].Trim());
        if (string.IsNullOrWhiteSpace(artist))
        {
            artist = TryRepairUtf8Mojibake(fallbackArtist);
        }
        if (string.IsNullOrWhiteSpace(title))
        {
            title = value;
        }
        return (artist, title);
    }

    private MediaPlaybackStatus GetCurrentMediaPlaybackStatus()
    {
        if (_mediaPlayer is null)
        {
            return MediaPlaybackStatus.Changing;
        }

        var playbackState = _mediaPlayer.PlaybackSession.PlaybackState;
        return playbackState switch
        {
            MediaPlaybackState.Playing => MediaPlaybackStatus.Playing,
            MediaPlaybackState.Paused => MediaPlaybackStatus.Paused,
            MediaPlaybackState.None => MediaPlaybackStatus.Stopped,
            _ => MediaPlaybackStatus.Changing,
        };
    }

    private MediaPlaybackStatus ResolveSmtcStatusForMetadataUpdate()
    {
        var current = GetCurrentMediaPlaybackStatus();
        if (
            current == MediaPlaybackStatus.Changing
            && string.Equals(_lastStatus, "Playing", StringComparison.OrdinalIgnoreCase)
        )
        {
            return MediaPlaybackStatus.Playing;
        }

        if (
            current == MediaPlaybackStatus.Stopped
            && string.Equals(_lastStatus, "Playing", StringComparison.OrdinalIgnoreCase)
        )
        {
            return MediaPlaybackStatus.Playing;
        }

        return current;
    }

    private void StartIcyMetadataMonitor(string url)
    {
        StopIcyMetadataMonitor();
        _icyMetadataCts = new CancellationTokenSource();
        var token = _icyMetadataCts.Token;
        _icyMetadataTask = Task.Run(() => RunIcyMetadataLoopAsync(url, token), token);
    }

    private void StopIcyMetadataMonitor()
    {
        try
        {
            _icyMetadataCts?.Cancel();
        }
        catch
        {
            // Ignore cancellation errors.
        }
        finally
        {
            _icyMetadataCts?.Dispose();
            _icyMetadataCts = null;
            _icyMetadataTask = null;
        }
    }

    private async Task RunIcyMetadataLoopAsync(string url, CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            try
            {
                var streamHadIcy = await TryReadIcyMetadataAsync(url, ct);
                if (!streamHadIcy)
                {
                    return;
                }
            }
            catch (OperationCanceledException)
            {
                return;
            }
            catch
            {
                // Retry after a short backoff.
            }

            try
            {
                await Task.Delay(TimeSpan.FromSeconds(2), ct);
            }
            catch (OperationCanceledException)
            {
                return;
            }
        }
    }

    private async Task<bool> TryReadIcyMetadataAsync(string url, CancellationToken ct)
    {
        using var request = new HttpRequestMessage(HttpMethod.Get, url);
        request.Headers.TryAddWithoutValidation("Icy-MetaData", "1");
        request.Headers.UserAgent.ParseAdd("RadioBrowserSMTCHost/1.0");

        using var response = await _icyHttpClient.SendAsync(
            request,
            HttpCompletionOption.ResponseHeadersRead,
            ct
        );
        response.EnsureSuccessStatusCode();

        if (!TryGetIcyMetaInt(response, out var metaint) || metaint <= 0)
        {
            return false;
        }

        var preferredEncoding = TryResolveIcyCharset(response) ?? _defaultStreamEncoding;
        await using var stream = await response.Content.ReadAsStreamAsync(ct);
        var audioSkipBuffer = new byte[Math.Min(metaint, 8192)];
        byte[] metadataBuffer = [];

        while (!ct.IsCancellationRequested)
        {
            if (!await SkipExactlyAsync(stream, audioSkipBuffer, metaint, ct))
            {
                return true;
            }

            var lengthByte = stream.ReadByte();
            if (lengthByte < 0)
            {
                return true;
            }

            var metadataLength = lengthByte * 16;
            if (metadataLength <= 0)
            {
                continue;
            }

            if (metadataBuffer.Length < metadataLength)
            {
                metadataBuffer = new byte[metadataLength];
            }

            if (
                !await ReadExactlyAsync(
                    stream,
                    metadataBuffer,
                    metadataLength,
                    ct
                )
            )
            {
                return true;
            }

            var nowPlaying = ExtractNowPlayingFromIcyBlock(
                metadataBuffer,
                metadataLength,
                preferredEncoding
            );
            if (string.IsNullOrWhiteSpace(nowPlaying))
            {
                continue;
            }

            await ApplyIcyNowPlayingAsync(url, nowPlaying);
        }

        return true;
    }

    private static bool TryGetIcyMetaInt(HttpResponseMessage response, out int metaint)
    {
        metaint = 0;

        if (
            response.Headers.TryGetValues("icy-metaint", out var values)
            || response.Content.Headers.TryGetValues("icy-metaint", out values)
        )
        {
            var raw = values.FirstOrDefault();
            return int.TryParse(raw, out metaint);
        }

        return false;
    }

    private static async Task<bool> SkipExactlyAsync(
        Stream stream,
        byte[] buffer,
        int bytesToSkip,
        CancellationToken ct
    )
    {
        var remaining = bytesToSkip;
        while (remaining > 0)
        {
            var toRead = Math.Min(remaining, buffer.Length);
            var read = await stream.ReadAsync(buffer.AsMemory(0, toRead), ct);
            if (read <= 0)
            {
                return false;
            }
            remaining -= read;
        }

        return true;
    }

    private static async Task<bool> ReadExactlyAsync(
        Stream stream,
        byte[] buffer,
        int length,
        CancellationToken ct
    )
    {
        var offset = 0;
        while (offset < length)
        {
            var read = await stream.ReadAsync(
                buffer.AsMemory(offset, length - offset),
                ct
            );
            if (read <= 0)
            {
                return false;
            }
            offset += read;
        }

        return true;
    }

    private static string ExtractNowPlayingFromIcyBlock(
        byte[] buffer,
        int length,
        Encoding? preferredEncoding = null
    )
    {
        if (buffer is null || length <= 0)
        {
            return string.Empty;
        }

        var titleBytes = TryExtractIcyStreamTitleBytes(buffer, length);
        if (titleBytes.Length == 0)
        {
            return string.Empty;
        }

        return DecodeIcyTitleBytes(titleBytes, preferredEncoding).Trim();
    }

    private static byte[] TryExtractIcyStreamTitleBytes(byte[] buffer, int length)
    {
        const string marker = "StreamTitle='";
        var markerBytes = Encoding.ASCII.GetBytes(marker);
        var markerIndex = IndexOfAsciiIgnoreCase(buffer, length, markerBytes);
        if (markerIndex < 0)
        {
            return [];
        }

        var valueStart = markerIndex + markerBytes.Length;
        if (valueStart >= length)
        {
            return [];
        }

        var valueEnd = valueStart;
        while (valueEnd < length && buffer[valueEnd] != (byte)'\'')
        {
            valueEnd++;
        }

        if (valueEnd <= valueStart)
        {
            return [];
        }

        var result = new byte[valueEnd - valueStart];
        System.Buffer.BlockCopy(buffer, valueStart, result, 0, result.Length);
        return result;
    }

    private static int IndexOfAsciiIgnoreCase(byte[] haystack, int length, byte[] needle)
    {
        if (needle.Length == 0 || length < needle.Length)
        {
            return -1;
        }

        for (var i = 0; i <= length - needle.Length; i++)
        {
            var match = true;
            for (var j = 0; j < needle.Length; j++)
            {
                var h = ToLowerAscii(haystack[i + j]);
                var n = ToLowerAscii(needle[j]);
                if (h != n)
                {
                    match = false;
                    break;
                }
            }

            if (match)
            {
                return i;
            }
        }

        return -1;
    }

    private static byte ToLowerAscii(byte value)
    {
        return value is >= (byte)'A' and <= (byte)'Z'
            ? (byte)(value + 32)
            : value;
    }

    private static string DecodeIcyTitleBytes(byte[] bytes, Encoding? preferredEncoding = null)
    {
        if (bytes is null || bytes.Length == 0)
        {
            return string.Empty;
        }

        if (preferredEncoding is not null)
        {
            var preferred = preferredEncoding.GetString(bytes).Replace("\0", "").Trim();
            return TryRepairUtf8Mojibake(preferred);
        }

        try
        {
            var utf8 = Utf8Strict.GetString(bytes).Replace("\0", "").Trim();
            return TryRepairUtf8Mojibake(utf8);
        }
        catch
        {
            // Ignore strict UTF-8 failures.
        }

        var latin1 = Encoding.Latin1.GetString(bytes).Replace("\0", "").Trim();
        return TryRepairUtf8Mojibake(latin1);
    }

    private static string TryRepairUtf8Mojibake(string text)
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            return text;
        }

        // 1) Common UTF-8 interpreted as latin1/cp1252 (e.g. å¼ éå²³).
        if (LooksLikeUtf8AsLatin1(text))
        {
            try
            {
                var raw = Encoding.Latin1.GetBytes(text);
                var repaired = Utf8Strict.GetString(raw).Trim();
                if (!string.IsNullOrWhiteSpace(repaired))
                {
                    return repaired;
                }
            }
            catch
            {
                // Ignore and continue with other repair paths.
            }
        }

        // 2) CJK bytes interpreted as single-byte text (e.g. *×ÁÁ / ËïÕÊ).
        var cjkRepaired = TryRepairCjkFromSingleByteMojibake(text);
        if (!string.Equals(cjkRepaired, text, StringComparison.Ordinal))
        {
            return cjkRepaired;
        }

        return text;
    }

    private static string TryRepairCjkFromSingleByteMojibake(string text)
    {
        if (!LooksLikeSingleByteMojibake(text) || ContainsCjkOrKanaOrHangul(text))
        {
            return text;
        }

        Encoding[] sourceEncodings = [Encoding.Latin1, Encoding.GetEncoding(1252)];
        var targetEncodingNames = new[] { "gb18030", "big5", "shift_jis", "euc-kr" };

        foreach (var source in sourceEncodings)
        {
            byte[] raw;
            try
            {
                raw = source.GetBytes(text);
            }
            catch
            {
                continue;
            }

            foreach (var targetName in targetEncodingNames)
            {
                Encoding? target = null;
                try
                {
                    target = Encoding.GetEncoding(targetName);
                }
                catch
                {
                    // Ignore unsupported code pages.
                }

                if (target is null)
                {
                    continue;
                }

                string repaired;
                try
                {
                    repaired = target.GetString(raw).Trim();
                }
                catch
                {
                    continue;
                }

                if (ContainsCjkOrKanaOrHangul(repaired))
                {
                    return repaired;
                }
            }
        }

        return text;
    }

    private static bool LooksLikeUtf8AsLatin1(string text)
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            return false;
        }

        var hasMojibakeMarkers =
            text.Contains('Ã')
            || text.Contains('Â')
            || text.Contains('Ð')
            || text.Contains('Ñ')
            || text.Contains('å')
            || text.Contains('æ')
            || text.Contains('ç')
            || text.Contains('é')
            || text.Contains('ï');

        if (!hasMojibakeMarkers)
        {
            return false;
        }

        foreach (var c in text)
        {
            if ((c >= '\u4E00' && c <= '\u9FFF') || (c >= '\u3040' && c <= '\u30FF'))
            {
                return false;
            }
        }

        return true;
    }

    private static bool LooksLikeSingleByteMojibake(string text)
    {
        var extendedCount = 0;
        foreach (var c in text)
        {
            if (c >= '\u00A0' && c <= '\u00FF')
            {
                extendedCount++;
            }
        }

        if (extendedCount < 2)
        {
            return false;
        }

        return
            text.Contains('×')
            || text.Contains('Á')
            || text.Contains('Ë')
            || text.Contains('Ê')
            || text.Contains('Ò')
            || text.Contains('Õ')
            || text.Contains('°')
            || text.Contains('£')
            || text.Contains('¤')
            || text.Contains('¥');
    }

    private static bool ContainsCjkOrKanaOrHangul(string text)
    {
        foreach (var c in text)
        {
            if ((c >= '\u4E00' && c <= '\u9FFF') || (c >= '\u3040' && c <= '\u30FF') || (c >= '\uAC00' && c <= '\uD7AF'))
            {
                return true;
            }
        }

        return false;
    }

    private static Encoding? TryResolveIcyCharset(HttpResponseMessage response)
    {
        var raw =
            response.Headers.TryGetValues("icy-charset", out var headerValues)
                ? headerValues.FirstOrDefault()
                : null;

        if (string.IsNullOrWhiteSpace(raw))
        {
            raw = response.Content.Headers.ContentType?.CharSet;
        }

        if (string.IsNullOrWhiteSpace(raw))
        {
            return null;
        }

        var charset = raw.Trim().Trim('"', '\'');
        try
        {
            return Encoding.GetEncoding(charset);
        }
        catch
        {
            return null;
        }
    }

    private static Encoding? ResolveDefaultStreamEncoding()
    {
        var raw = Environment.GetEnvironmentVariable("RADIO_DEFAULT_STREAM_ENCODING");
        if (string.IsNullOrWhiteSpace(raw))
        {
            return null;
        }

        var name = raw.Trim();
        try
        {
            return Encoding.GetEncoding(name);
        }
        catch
        {
            return null;
        }
    }

    private async Task ApplyIcyNowPlayingAsync(string sourceUrl, string nowPlaying)
    {
        await Dispatcher.InvokeAsync(() =>
        {
            if (
                string.IsNullOrWhiteSpace(_lastUrl)
                || !string.Equals(_lastUrl, sourceUrl, StringComparison.OrdinalIgnoreCase)
            )
            {
                return;
            }

            var (artist, title) = ParseArtistAndTitle(nowPlaying, _lastArtist);
            if (
                string.Equals(_lastArtist, artist, StringComparison.Ordinal)
                && string.Equals(_lastTitle, title, StringComparison.Ordinal)
            )
            {
                return;
            }

            var status = ResolveSmtcStatusForMetadataUpdate();
            SetMedia(title, artist, status);
            _lastTitle = title;
            _lastArtist = artist;
            _lastStatus = GetCurrentLogicalStatus();
            _lastUpdatedAt = DateTimeOffset.UtcNow;
            StateText.Text = $"Status: {ToUiStatus(_lastStatus)}";
            UpdateNowPlayingUi(artist, title);
        });
    }

    private string GetCurrentLogicalStatus()
    {
        if (_mediaPlayer is null)
        {
            return "Connecting";
        }

        return ToLogicalStatus(_mediaPlayer.PlaybackSession.PlaybackState);
    }

    private static string ToLogicalStatus(MediaPlaybackStatus status)
    {
        return status switch
        {
            MediaPlaybackStatus.Playing => "Playing",
            MediaPlaybackStatus.Paused => "Paused",
            MediaPlaybackStatus.Stopped => "Stopped",
            _ => "Connecting",
        };
    }

    private static string ToLogicalStatus(MediaPlaybackState state)
    {
        return state switch
        {
            MediaPlaybackState.Playing => "Playing",
            MediaPlaybackState.Paused => "Paused",
            MediaPlaybackState.None => "Stopped",
            MediaPlaybackState.Opening => "Connecting",
            MediaPlaybackState.Buffering => "Connecting",
            _ => "Connecting",
        };
    }

    private static string ToUiStatus(MediaPlaybackStatus status)
    {
        return ToLogicalStatus(status);
    }

    private static string ToUiStatus(string status)
    {
        if (string.IsNullOrWhiteSpace(status))
        {
            return "Stopped";
        }
        return status;
    }
}
