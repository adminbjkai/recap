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
  };
};

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
