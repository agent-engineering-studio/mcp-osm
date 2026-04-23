using System.ClientModel;
using Microsoft.Agents.AI;
using Microsoft.Extensions.AI;
using ModelContextProtocol.Client;
using OpenAI;
using OsmAgent;
using OsmAgent.Models;

var builder = WebApplication.CreateBuilder(args);

// ── Configuration ─────────────────────────────────────────────────────
var ollamaBaseUrl = builder.Configuration["Ollama:BaseUrl"]
    ?? Environment.GetEnvironmentVariable("OLLAMA_BASE_URL")
    ?? "http://host.docker.internal:11434";
var ollamaModel = builder.Configuration["Ollama:Model"]
    ?? Environment.GetEnvironmentVariable("OLLAMA_LLM_MODEL")
    ?? "qwen2.5:7b";

var mcpUrl = builder.Configuration["Mcp:Url"]
    ?? Environment.GetEnvironmentVariable("MCP_SERVER_URL")
    ?? "http://osm-mcp:8080/sse";

var instructions = builder.Configuration["Agent:Instructions"]
    ?? """
    You are an OpenStreetMap-aware assistant. Answer user questions about places, addresses,
    routing, and neighbourhoods by calling the available MCP tools. Prefer calling tools over
    guessing. When you report routes, include distance in km and duration in minutes.
    When you report POIs, include the name, a short address, and the tool-reported category.
    Always keep answers concise and actionable.
    """;

builder.Services.AddCors(o => o.AddDefaultPolicy(p => p.AllowAnyOrigin().AllowAnyMethod().AllowAnyHeader()));
builder.Logging.AddSimpleConsole(o => { o.SingleLine = true; o.TimestampFormat = "HH:mm:ss "; });

// ── MCP client (shared, SSE over HTTP) ───────────────────────────────
// The MCP C# SDK (1.2.0) exposes HttpClientTransport for both SSE and the
// newer streamable-HTTP transports. The Python FastMCP server is launched
// with transport="sse", so we force HttpTransportMode.Sse here.
var mcpClient = await McpClient.CreateAsync(
    new HttpClientTransport(new HttpClientTransportOptions
    {
        Name = "osm-mcp",
        Endpoint = new Uri(mcpUrl),
        TransportMode = HttpTransportMode.Sse,
    }));

var mcpTools = await mcpClient.ListToolsAsync();
Console.WriteLine($"[osm-agent] Connected to MCP server — {mcpTools.Count} tools loaded");
foreach (var t in mcpTools)
{
    Console.WriteLine($"[osm-agent]  · {t.Name}");
}

// ── IChatClient over Ollama's OpenAI-compatible endpoint ─────────────
// Ollama exposes /v1/chat/completions; we point the OpenAI client at it.
var openAiClient = new OpenAIClient(
    new ApiKeyCredential("ollama"),
    new OpenAIClientOptions { Endpoint = new Uri($"{ollamaBaseUrl.TrimEnd('/')}/v1") });

IChatClient chatClient = openAiClient.GetChatClient(ollamaModel).AsIChatClient();

// Build the AIAgent with the MCP tools registered at construction time.
AIAgent agent = chatClient.AsAIAgent(
    instructions: instructions,
    name: "OsmAgent",
    tools: mcpTools.Cast<AITool>().ToList());

builder.Services.AddSingleton(agent);
builder.Services.AddSingleton(mcpClient);

// In-memory session registry — one conversation session per sessionId.
builder.Services.AddSingleton<ThreadRegistry>();

var app = builder.Build();
app.UseCors();

// ── HTTP API ──────────────────────────────────────────────────────────

app.MapGet("/health", () => Results.Ok(new { status = "healthy", model = ollamaModel, mcp = mcpUrl }));

app.MapGet("/tools", () => Results.Ok(mcpTools.Select(t => new { name = t.Name, description = t.Description })));

app.MapPost("/chat", async (ChatRequest req, AIAgent a, ThreadRegistry reg, CancellationToken ct) =>
{
    if (string.IsNullOrWhiteSpace(req.Message))
        return Results.BadRequest(new { error = "message is required" });

    var sessionId = req.SessionId ?? "default";
    var session = await reg.GetOrCreateAsync(sessionId, a, ct);
    var result = await a.RunAsync(req.Message, session, cancellationToken: ct);
    return Results.Ok(new OsmAgent.Models.ChatResponse(result.Text ?? result.ToString(), sessionId));
});

app.MapPost("/chat/stream", async (HttpContext ctx, ChatRequest req, AIAgent a, ThreadRegistry reg, CancellationToken ct) =>
{
    if (string.IsNullOrWhiteSpace(req.Message))
    {
        ctx.Response.StatusCode = 400;
        await ctx.Response.WriteAsJsonAsync(new { error = "message is required" }, ct);
        return;
    }

    ctx.Response.Headers.ContentType = "text/event-stream";
    ctx.Response.Headers["Cache-Control"] = "no-cache";

    var sessionId = req.SessionId ?? "default";
    var session = await reg.GetOrCreateAsync(sessionId, a, ct);
    await foreach (var update in a.RunStreamingAsync(req.Message, session, cancellationToken: ct))
    {
        var payload = System.Text.Json.JsonSerializer.Serialize(new { text = update.ToString() });
        await ctx.Response.WriteAsync($"data: {payload}\n\n", ct);
        await ctx.Response.Body.FlushAsync(ct);
    }
    await ctx.Response.WriteAsync("event: done\ndata: {}\n\n", ct);
});

// Ensure the MCP client is released on shutdown.
app.Lifetime.ApplicationStopping.Register(() =>
{
    try { mcpClient.DisposeAsync().AsTask().Wait(TimeSpan.FromSeconds(5)); } catch { /* ignored */ }
});

app.Run();
