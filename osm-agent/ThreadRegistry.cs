using System.Collections.Concurrent;
using Microsoft.Agents.AI;

namespace OsmAgent;

/// <summary>
/// Holds one <see cref="AgentSession"/> per session id so multi-turn
/// conversations keep history across HTTP requests.
/// </summary>
public sealed class ThreadRegistry
{
    private readonly ConcurrentDictionary<string, AgentSession> _sessions = new();

    public async Task<AgentSession> GetOrCreateAsync(
        string sessionId,
        AIAgent agent,
        CancellationToken ct = default)
    {
        if (_sessions.TryGetValue(sessionId, out var existing))
        {
            return existing;
        }

        var created = await agent.CreateSessionAsync(ct);
        return _sessions.GetOrAdd(sessionId, created);
    }

    public bool Drop(string sessionId) => _sessions.TryRemove(sessionId, out _);
}
