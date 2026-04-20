export type JobStage = {
  status?: string;
  started_at?: string;
  finished_at?: string;
  error?: string;
  [key: string]: unknown;
};

export type JobSummary = {
  job_id: string;
  original_filename?: string;
  source_path?: string;
  created_at?: string;
  updated_at?: string;
  status?: string;
  error?: string | null;
  stages: Record<string, JobStage>;
  artifacts: Record<string, boolean>;
  urls: {
    analysis_mp4: string;
    transcript: string;
    speaker_names: string;
    [key: string]: string | undefined;
  };
};

export type InsightsActionItem = {
  text: string;
  chapter_index?: number | null;
  timestamp_seconds?: number | null;
  owner?: string | null;
  due?: string | null;
};

export type InsightsChapter = {
  index: number;
  start_seconds: number;
  end_seconds: number;
  title: string;
  summary: string;
  bullets: string[];
  action_items: string[];
  speaker_focus: string[];
};

export type InsightsDoc = {
  version: number;
  provider: string;
  model: string;
  generated_at: string;
  sources: Record<string, string | null>;
  overview: {
    title: string;
    short_summary: string;
    detailed_summary: string;
    quick_bullets: string[];
  };
  chapters: InsightsChapter[];
  action_items: InsightsActionItem[];
};

export type InsightsLoadState =
  | { status: "loading" }
  | { status: "absent" }
  | { status: "error"; message: string; reason?: string }
  | { status: "loaded"; insights: InsightsDoc };

export type SourceEntry = {
  name: string;
  size_bytes: number;
  modified_at: string;
};

export type SourcesPayload = {
  sources_root: string | null;
  sources_root_exists: boolean;
  extensions: string[];
  sources: SourceEntry[];
};

export type EngineEntry = {
  id: string;
  label: string;
  category: string;
  default: boolean;
  available: boolean;
  note?: string;
};

export type EnginesPayload = {
  engines: EngineEntry[];
  default: string;
};

export type StartSourceSpec =
  | { kind: "sources-root"; name: string }
  | { kind: "absolute-path"; path: string };

export type StartJobRequest = {
  source: StartSourceSpec;
  engine: string;
};

export type StartJobResponse = {
  job_id: string;
  engine: string;
  react_detail: string;
  legacy_detail: string;
  started_at: string;
  stub?: boolean;
};

export type StartJobResult =
  | { kind: "accepted"; response: StartJobResponse }
  | { kind: "error"; message: string; reason?: string; status: number };

export type TranscriptSegment = {
  id?: number;
  start: number;
  end?: number;
  text: string;
  speaker?: unknown;
};

export type TranscriptPayload = {
  engine?: string;
  model?: string;
  language?: string;
  duration?: number;
  segments?: TranscriptSegment[];
  utterances?: TranscriptSegment[];
  words?: unknown[];
  [key: string]: unknown;
};

export type SpeakerNamesDoc = {
  version: 1;
  updated_at: string | null;
  speakers: Record<string, string>;
};

type ApiErrorBody = {
  error?: string;
  reason?: string;
};

let csrfToken: string | null = null;

async function parseJson<T>(response: Response): Promise<T> {
  const text = await response.text();
  if (!text) {
    return {} as T;
  }
  return JSON.parse(text) as T;
}

async function requestJson<T>(
  url: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(url, {
    cache: "no-store",
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.headers ?? {}),
    },
  });
  const body = await parseJson<T | ApiErrorBody>(response);
  if (!response.ok) {
    const apiBody = body as ApiErrorBody;
    const message = apiBody.error || `${response.status} ${response.statusText}`;
    throw new Error(message);
  }
  return body as T;
}

export async function getCsrf(force = false): Promise<string> {
  if (csrfToken && !force) {
    return csrfToken;
  }
  const payload = await requestJson<{ token: string }>("/api/csrf");
  csrfToken = payload.token;
  return csrfToken;
}

export function getJob(id: string): Promise<JobSummary> {
  return requestJson<JobSummary>(`/api/jobs/${encodeURIComponent(id)}`);
}

export function getJobs(): Promise<{ jobs: JobSummary[] }> {
  return requestJson<{ jobs: JobSummary[] }>("/api/jobs");
}

export function getTranscript(id: string): Promise<TranscriptPayload> {
  return requestJson<TranscriptPayload>(
    `/api/jobs/${encodeURIComponent(id)}/transcript`,
  );
}

export type InsightsFetchResult =
  | { kind: "loaded"; insights: InsightsDoc }
  | { kind: "absent" }
  | { kind: "error"; message: string; reason?: string };

export async function getInsights(id: string): Promise<InsightsFetchResult> {
  const response = await fetch(
    `/api/jobs/${encodeURIComponent(id)}/insights`,
    {
      cache: "no-store",
      headers: { Accept: "application/json" },
    },
  );
  const body = await parseJson<InsightsDoc | ApiErrorBody>(response);
  if (response.status === 404) {
    const reason = (body as ApiErrorBody).reason;
    if (reason === "no-insights") {
      return { kind: "absent" };
    }
    return {
      kind: "error",
      message:
        (body as ApiErrorBody).error ||
        `${response.status} ${response.statusText}`,
      reason,
    };
  }
  if (!response.ok) {
    const apiBody = body as ApiErrorBody;
    return {
      kind: "error",
      message: apiBody.error || `${response.status} ${response.statusText}`,
      reason: apiBody.reason,
    };
  }
  return { kind: "loaded", insights: body as InsightsDoc };
}

export function getSources(): Promise<SourcesPayload> {
  return requestJson<SourcesPayload>("/api/sources");
}

export function getEngines(): Promise<EnginesPayload> {
  return requestJson<EnginesPayload>("/api/engines");
}

async function postStartJob(
  body: StartJobRequest,
  token: string,
): Promise<Response> {
  return fetch("/api/jobs/start", {
    method: "POST",
    cache: "no-store",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "X-Recap-Token": token,
    },
    body: JSON.stringify(body),
  });
}

export async function startJob(
  body: StartJobRequest,
): Promise<StartJobResult> {
  let token = await getCsrf();
  let response = await postStartJob(body, token);
  if (response.status === 403) {
    // Token may have rotated mid-session; refresh once before giving up.
    token = await getCsrf(true);
    response = await postStartJob(body, token);
  }
  const parsed = await parseJson<StartJobResponse | ApiErrorBody>(response);
  if (!response.ok) {
    const apiBody = parsed as ApiErrorBody;
    return {
      kind: "error",
      status: response.status,
      message:
        apiBody.error || `${response.status} ${response.statusText}`,
      reason: apiBody.reason,
    };
  }
  return { kind: "accepted", response: parsed as StartJobResponse };
}

export function getSpeakerNames(id: string): Promise<SpeakerNamesDoc> {
  return requestJson<SpeakerNamesDoc>(
    `/api/jobs/${encodeURIComponent(id)}/speaker-names`,
  );
}

async function postSpeakerNames(
  id: string,
  speakers: Record<string, string>,
  token: string,
): Promise<Response> {
  return fetch(`/api/jobs/${encodeURIComponent(id)}/speaker-names`, {
    method: "POST",
    cache: "no-store",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "X-Recap-Token": token,
    },
    body: JSON.stringify({ speakers }),
  });
}

export async function saveSpeakerNames(
  id: string,
  speakers: Record<string, string>,
): Promise<SpeakerNamesDoc> {
  let token = await getCsrf();
  let response = await postSpeakerNames(id, speakers, token);
  if (response.status === 403) {
    token = await getCsrf(true);
    response = await postSpeakerNames(id, speakers, token);
  }
  const body = await parseJson<SpeakerNamesDoc | ApiErrorBody>(response);
  if (!response.ok) {
    const apiBody = body as ApiErrorBody;
    throw new Error(apiBody.error || `${response.status} ${response.statusText}`);
  }
  return body as SpeakerNamesDoc;
}
