namespace OsmAgent.Models;

public record ChatRequest(string Message, string? SessionId);

public record ChatResponse(string Answer, string SessionId);
