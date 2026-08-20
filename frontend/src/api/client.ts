export interface Server {
  id: string;
  cpu_units_per_tick: number;
  mem_mb: number;
  rate_limit_per_sec: number;
}

export type ServerCreate = Server;

export interface ServerUpdate {
  cpu_units_per_tick: number;
  mem_mb: number;
  rate_limit_per_sec: number;
}

export interface RunSummary {
  status: "completed";
  total_requests: number;
  started: number;
  finished: number;
  dropped: number;
  avg_wait_ticks: number | null;
  p50_wait_ticks: number | null;
  p95_wait_ticks: number | null;
  max_wait_ticks: number | null;
}

export interface StrategyInfo {
  id: string;
  label: string;
  default: boolean;
}

export interface StrategiesResponse {
  strategies: StrategyInfo[];
}

export interface ServerMetrics {
  server_id: string;
  requests_handled: number;
  work_units_total: number | null;
  busy_ticks: number;
  /** Occupancy/CPU-pressure proxy, not literal CPU utilization. */
  busy_time_ratio: number | null;
  cpu_units_per_tick: number | null;
}

export interface MetricsResponse {
  context_available: boolean;
  strategy_used: string | null;
  total_requests: number;
  started: number;
  finished: number;
  dropped: number;
  dropped_rate: number | null;
  duration_ticks: number;
  throughput_requests_per_tick: number | null;
  peak_queue_depth: number;
  avg_queue_depth: number | null;
  configured_server_count: number | null;
  idle_configured_server_ids: string[] | null;
  /** Occupancy/CPU-pressure proxy, not literal CPU utilization. */
  avg_cluster_busy_ratio: number | null;
  servers: ServerMetrics[];
}

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isValidationErrorItem(value: unknown): value is { msg?: unknown } {
  return isRecord(value);
}

/**
 * FastAPI's own 422 (RequestValidationError) returns detail as an array of
 * {loc, msg, type} objects; every custom domain-error handler in this project
 * returns detail as a plain string. Both shapes are normalized to one string
 * here so callers never need to branch on it.
 */
function extractDetail(body: unknown, status: number): string {
  if (isRecord(body)) {
    if (typeof body.detail === "string") {
      return body.detail;
    }
    if (Array.isArray(body.detail)) {
      const messages = body.detail
        .filter(isValidationErrorItem)
        .map((item) => (typeof item.msg === "string" ? item.msg : JSON.stringify(item)));
      if (messages.length > 0) {
        return messages.join("; ");
      }
    }
  }
  return `Request failed with status ${status}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...init,
    });
  } catch {
    throw new ApiError(0, "Network error: unable to reach the server.");
  }

  if (response.status === 204) {
    return undefined as T;
  }

  let body: unknown;
  const text = await response.text();
  if (text.length > 0) {
    try {
      body = JSON.parse(text);
    } catch {
      body = undefined;
    }
  }

  if (!response.ok) {
    throw new ApiError(response.status, extractDetail(body, response.status));
  }

  return body as T;
}

export function listServers(): Promise<Server[]> {
  return request<Server[]>("/api/servers");
}

export function createServer(data: ServerCreate): Promise<Server> {
  return request<Server>("/api/servers", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function updateServer(id: string, data: ServerUpdate): Promise<Server> {
  return request<Server>(`/api/servers/${encodeURIComponent(id)}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export function deleteServer(id: string): Promise<void> {
  return request<void>(`/api/servers/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export function runSimulation(strategy?: string): Promise<RunSummary> {
  const path = strategy ? `/api/simulations/run?strategy=${encodeURIComponent(strategy)}` : "/api/simulations/run";
  return request<RunSummary>(path, { method: "POST" });
}

export function getLatestSimulation(): Promise<RunSummary> {
  return request<RunSummary>("/api/simulations/latest");
}

export function getStrategies(): Promise<StrategiesResponse> {
  return request<StrategiesResponse>("/api/simulations/strategies");
}

export function getLatestMetrics(): Promise<MetricsResponse> {
  return request<MetricsResponse>("/api/simulations/latest/metrics");
}
