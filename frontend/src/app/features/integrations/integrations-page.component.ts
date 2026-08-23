import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { TranslateModule } from '@ngx-translate/core';
import { CodeSnippetComponent } from '@shared/components/code-snippet/code-snippet.component';
import {
  IntegrationToken,
  IntegrationsService,
  StreamInfo,
  WebhookSubscription,
} from '@core/services/integrations.service';
import {
  Example,
  mcpExamples,
  streamExamples,
  webhookExamples,
} from './integration-examples';

/** Which integration the page is showing. */
type IntegrationTab = 'webhooks' | 'mcp' | 'streaming';

/**
 * Integrations: outward connections from this instance.
 *
 * Three of them, presented as tabs because they are alternatives rather than
 * steps: a webhook pushes events to a receiver, the protocol server lets an
 * agent pull them, and the streams let a broker or a terminal subscribe. Most
 * deployments want one of the three.
 *
 * A secret and a token are shown exactly once, when they are issued. That is
 * not an inconvenience to work around: a credential the interface can display
 * at any time is a credential that leaks through every screen share and
 * screenshot that catches it.
 */
@Component({
  selector: 'app-integrations-page',
  standalone: true,
  imports: [CommonModule, FormsModule, TranslateModule, CodeSnippetComponent],
  templateUrl: './integrations-page.component.html',
  styleUrl: './integrations-page.component.scss',
})
export class IntegrationsPageComponent implements OnInit {
  private readonly service = inject(IntegrationsService);

  readonly tab = signal<IntegrationTab>('webhooks');

  readonly webhooks = signal<WebhookSubscription[]>([]);
  readonly tokens = signal<IntegrationToken[]>([]);
  readonly eventTypes = signal<string[]>([]);
  readonly eventFamilies = signal<string[]>([]);

  /** What the server says can be subscribed to. Null when streaming is off. */
  readonly streamInfo = signal<StreamInfo | null>(null);

  readonly isLoading = signal(true);
  readonly message = signal<string | null>(null);
  readonly errorMessage = signal<string | null>(null);

  // New subscription
  readonly newName = signal('');
  readonly newUrl = signal('');
  readonly newTypes = signal<string[]>([]);

  // New token
  readonly newTokenName = signal('');
  readonly newTokenScopes = signal<string[]>(['events:read']);

  /**
   * What a token can be granted.
   *
   * The first three read or manage records. The last two are different in
   * kind: one switches a camera on and the other watches what it sees, and
   * both are decisions about a room rather than queries, so neither is ever
   * implied by the others and each has to be ticked deliberately. A token
   * without them can read everything the camera saw and still not turn it on
   * or look through it.
   */
  readonly availableScopes = [
    'events:read',
    'objects:read',
    'events:manage',
    'camera:control',
    'camera:view',
  ];

  /**
   * A credential just issued, shown once.
   *
   * Held here rather than on the record it belongs to, because the record is
   * refreshed from the server and the value is not part of it.
   */
  readonly revealedSecret = signal('');
  readonly revealedToken = signal('');

  readonly selectedWebhookExample = signal('node');
  readonly selectedMcpExample = signal('claude');
  readonly selectedStreamExample = signal('shell');

  /**
   * Where an agent or a subscriber should reach this instance.
   *
   * Defaults to the origin the browser is already using, which is right when
   * the agent runs on this machine and wrong when it does not. Editable for
   * that reason: a container or another host cannot resolve localhost here.
   */
  readonly baseUrl = signal(this.defaultBaseUrl());

  readonly webhookSnippets = computed<Example[]>(() =>
    webhookExamples(this.revealedSecret()),
  );

  readonly mcpSnippets = computed<Example[]>(() =>
    mcpExamples(this.baseUrl().replace(/\/+$/, ''), this.revealedToken()),
  );

  readonly currentWebhookSnippet = computed<Example | undefined>(() =>
    this.webhookSnippets().find((e) => e.id === this.selectedWebhookExample()),
  );

  readonly currentMcpSnippet = computed<Example | undefined>(() =>
    this.mcpSnippets().find((e) => e.id === this.selectedMcpExample()),
  );

  readonly streamSnippets = computed<Example[]>(() =>
    streamExamples(this.baseUrl().replace(/\/+$/, ''), this.revealedToken()),
  );

  readonly currentStreamSnippet = computed<Example | undefined>(() =>
    this.streamSnippets().find((e) => e.id === this.selectedStreamExample()),
  );

  /**
   * The topic table, in the order the server lists it.
   *
   * Read from the response rather than hard coded, so a topic added to the
   * backend appears here with no change to this file.
   */
  readonly streamTopics = computed<Array<{ name: string; template: string }>>(() => {
    const topics = this.streamInfo()?.broker.topics ?? {};
    return Object.entries(topics).map(([name, template]) => ({ name, template }));
  });

  /** Whether any subscription is switched on, which is what the toggle reflects. */
  readonly webhooksActive = computed(() => this.webhooks().some((w) => w.isActive));

  /** Whether any token is usable, which is what the protocol toggle reflects. */
  readonly mcpActive = computed(() => this.tokens().some((t) => t.isActive));

  /**
   * Whether anything can be subscribed to.
   *
   * The HTTP stream works without a broker, so the tab reads active when
   * either is available rather than only when the broker is up.
   */
  readonly streamingActive = computed(() => {
    const info = this.streamInfo();
    return !!info && (info.broker.connected || info.enabled);
  });

  private defaultBaseUrl(): string {
    // The API is reached through the same origin in this deployment, so the
    // browser's own origin is the best first guess.
    return typeof window !== 'undefined' ? window.location.origin : 'http://localhost:4202';
  }

  ngOnInit(): void {
    this.reload();
  }

  private reload(): void {
    this.isLoading.set(true);

    this.service.listWebhooks().subscribe({
      next: (items) => {
        this.webhooks.set(items);
        this.isLoading.set(false);
      },
      error: () => this.isLoading.set(false),
    });

    this.service.listTokens().subscribe({
      next: (items) => this.tokens.set(items),
      error: () => undefined,
    });

    this.service.getStreamInfo().subscribe({
      next: (info) => this.streamInfo.set(info),
      error: () => this.streamInfo.set(null),
    });

    this.service.listEventTypes().subscribe({
      next: (response) => {
        this.eventTypes.set(response.types);
        this.eventFamilies.set(response.families);
      },
      error: () => undefined,
    });
  }

  selectTab(tab: IntegrationTab): void {
    this.tab.set(tab);
  }

  // Webhooks

  toggleType(type: string): void {
    const current = this.newTypes();
    this.newTypes.set(
      current.includes(type) ? current.filter((t) => t !== type) : [...current, type],
    );
  }

  createWebhook(): void {
    const name = this.newName().trim();
    const url = this.newUrl().trim();
    if (!name || !url) {
      return;
    }

    this.service.createWebhook(name, url, this.newTypes()).subscribe({
      next: (created) => {
        this.webhooks.update((items) => [...items, created]);
        // Shown once, here. It is not readable afterwards.
        this.revealedSecret.set(created.secret ?? '');
        this.newName.set('');
        this.newUrl.set('');
        this.newTypes.set([]);
        this.message.set('integrations.webhooks.created');
      },
      error: (err) => this.errorMessage.set(err?.error?.detail ?? 'integrations.errors.failed'),
    });
  }

  setWebhookActive(subscription: WebhookSubscription, isActive: boolean): void {
    this.service.updateWebhook(subscription.id, { isActive }).subscribe({
      next: (updated) =>
        this.webhooks.update((items) =>
          items.map((w) => (w.id === updated.id ? updated : w)),
        ),
      error: (err) => this.errorMessage.set(err?.error?.detail ?? 'integrations.errors.failed'),
    });
  }

  rotateSecret(subscription: WebhookSubscription): void {
    this.service.rotateWebhookSecret(subscription.id).subscribe({
      next: (updated) => {
        this.revealedSecret.set(updated.secret ?? '');
        this.message.set('integrations.webhooks.rotated');
      },
      error: (err) => this.errorMessage.set(err?.error?.detail ?? 'integrations.errors.failed'),
    });
  }

  testWebhook(subscription: WebhookSubscription): void {
    this.service.testWebhook(subscription.id).subscribe({
      next: (response) => {
        this.message.set(response.message);
        this.reload();
      },
      error: (err) => this.errorMessage.set(err?.error?.detail ?? 'integrations.errors.failed'),
    });
  }

  deleteWebhook(subscription: WebhookSubscription): void {
    this.service.deleteWebhook(subscription.id).subscribe({
      next: () =>
        this.webhooks.update((items) => items.filter((w) => w.id !== subscription.id)),
      error: (err) => this.errorMessage.set(err?.error?.detail ?? 'integrations.errors.failed'),
    });
  }

  // Tokens

  toggleScope(scope: string): void {
    const current = this.newTokenScopes();
    this.newTokenScopes.set(
      current.includes(scope) ? current.filter((s) => s !== scope) : [...current, scope],
    );
  }

  createToken(): void {
    const name = this.newTokenName().trim();
    if (!name) {
      return;
    }

    this.service.createToken(name, this.newTokenScopes()).subscribe({
      next: (created) => {
        this.tokens.update((items) => [...items, created]);
        this.revealedToken.set(created.token ?? '');
        this.newTokenName.set('');
        this.message.set('integrations.mcp.created');
      },
      error: (err) => this.errorMessage.set(err?.error?.detail ?? 'integrations.errors.failed'),
    });
  }

  setTokenActive(token: IntegrationToken, isActive: boolean): void {
    this.service.setTokenActive(token.id, isActive).subscribe({
      next: (updated) =>
        this.tokens.update((items) => items.map((t) => (t.id === updated.id ? updated : t))),
      error: (err) => this.errorMessage.set(err?.error?.detail ?? 'integrations.errors.failed'),
    });
  }

  deleteToken(token: IntegrationToken): void {
    this.service.deleteToken(token.id).subscribe({
      next: () => this.tokens.update((items) => items.filter((t) => t.id !== token.id)),
      error: (err) => this.errorMessage.set(err?.error?.detail ?? 'integrations.errors.failed'),
    });
  }

  dismiss(): void {
    this.message.set(null);
    this.errorMessage.set(null);
  }

  /** Stop showing a credential, once it has been copied. */
  hideCredentials(): void {
    this.revealedSecret.set('');
    this.revealedToken.set('');
  }
}
