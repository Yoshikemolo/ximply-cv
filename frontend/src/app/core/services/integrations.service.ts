import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '@env';

/** A registered webhook client. */
export interface WebhookSubscription {
  id: string;
  name: string;
  url: string;
  eventTypes: string[];
  isActive: boolean;
  lastDeliveryAt?: string;
  lastStatus?: number;
  lastError?: string;
  failureCount: number;
  createdAt: string;
  /** Present only in the response that created or rotated it. */
  secret?: string;
}

/** A credential issued to one external client. */
export interface IntegrationToken {
  id: string;
  name: string;
  prefix: string;
  scopes: string[];
  isActive: boolean;
  lastUsedAt?: string;
  expiresAt?: string;
  createdAt: string;
  /** Present only in the response that issued it. */
  token?: string;
}

/** What the broker is doing, and where a subscriber reaches it. */
export interface StreamBroker {
  enabled: boolean;
  connected: boolean;
  host: string;
  port: number;
  instance: string;
  publishesCaptures: boolean;
  publishesFrames: boolean;
  published: number;
  dropped: number;
  /** Topic templates keyed by what they carry, as the server names them. */
  topics: Record<string, string>;
}

/** One subscribable HTTP endpoint, described by the server. */
export interface StreamEndpoint {
  path: string;
  mediaType: string;
  scope: string;
  /** Frames only: whether the deployment allows watching a camera at all. */
  enabled?: boolean;
  maxFps?: number;
  maxSide?: number;
}

/**
 * What can be subscribed to, and how.
 *
 * The page builds its topic table and its examples from this rather than
 * hard coding them, so a topic added to the backend appears with no change
 * here.
 */
export interface StreamInfo {
  enabled: boolean;
  owner: string;
  broker: StreamBroker;
  endpoints: {
    events: StreamEndpoint;
    camera: StreamEndpoint;
  };
  keepaliveSeconds: number;
  subscribers: number;
  dropped: number;
}

/** One recorded event, shaped as an OpenTelemetry log record. */
export interface VisionEvent {
  id: string;
  eventName: string;
  timestampNanos: number;
  severityNumber: number;
  severityText: string;
  body: Record<string, unknown>;
  attributes: Record<string, unknown>;
  subjectName?: string;
  confidence?: number;
  captureUrl?: string;
  occurredAt: string;
}

/**
 * Everything the Integrations page talks to.
 *
 * One service rather than three, because the page presents webhooks, tokens and
 * events as one subject and splitting them would only move the joins into the
 * component.
 */
@Injectable({ providedIn: 'root' })
export class IntegrationsService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiUrl}/${environment.apiVersion}`;

  // Webhooks

  listWebhooks(): Observable<WebhookSubscription[]> {
    return this.http.get<WebhookSubscription[]>(`${this.base}/webhooks`);
  }

  createWebhook(name: string, url: string, eventTypes: string[]): Observable<WebhookSubscription> {
    return this.http.post<WebhookSubscription>(`${this.base}/webhooks`, {
      name,
      url,
      event_types: eventTypes,
    });
  }

  updateWebhook(id: string, changes: Partial<WebhookSubscription>): Observable<WebhookSubscription> {
    return this.http.put<WebhookSubscription>(`${this.base}/webhooks/${id}`, {
      name: changes.name,
      url: changes.url,
      event_types: changes.eventTypes,
      is_active: changes.isActive,
    });
  }

  /** Replace the secret. The receiver must be updated first, or it will reject. */
  rotateWebhookSecret(id: string): Observable<WebhookSubscription> {
    return this.http.post<WebhookSubscription>(`${this.base}/webhooks/${id}/rotate`, {});
  }

  /** Send a signed test delivery, so a receiver can be verified before it matters. */
  testWebhook(id: string): Observable<{ message: string }> {
    return this.http.post<{ message: string }>(`${this.base}/webhooks/${id}/test`, {});
  }

  deleteWebhook(id: string): Observable<{ message: string }> {
    return this.http.delete<{ message: string }>(`${this.base}/webhooks/${id}`);
  }

  // Integration tokens

  listTokens(): Observable<IntegrationToken[]> {
    return this.http.get<IntegrationToken[]>(`${this.base}/integration-tokens`);
  }

  createToken(name: string, scopes: string[]): Observable<IntegrationToken> {
    return this.http.post<IntegrationToken>(`${this.base}/integration-tokens`, {
      name,
      scopes,
    });
  }

  setTokenActive(id: string, isActive: boolean): Observable<IntegrationToken> {
    return this.http.put<IntegrationToken>(
      `${this.base}/integration-tokens/${id}?is_active=${isActive}`,
      {},
    );
  }

  deleteToken(id: string): Observable<{ message: string }> {
    return this.http.delete<{ message: string }>(`${this.base}/integration-tokens/${id}`);
  }

  // Streaming

  /** The broker state, the topic templates and the endpoint paths. */
  getStreamInfo(): Observable<StreamInfo> {
    return this.http.get<StreamInfo>(`${this.base}/stream/info`);
  }

  // Events

  listEventTypes(): Observable<{ types: string[]; families: string[] }> {
    return this.http.get<{ types: string[]; families: string[] }>(`${this.base}/events/types`);
  }

  listEvents(limit = 20): Observable<{ items: VisionEvent[]; total: number }> {
    return this.http.get<{ items: VisionEvent[]; total: number }>(
      `${this.base}/events?page_size=${limit}`,
    );
  }
}
