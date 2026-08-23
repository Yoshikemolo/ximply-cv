import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { TranslateModule } from '@ngx-translate/core';
import { AuthService } from '@core/services/auth.service';
import { environment } from '@env';

/** What the server reports about its protocol endpoint. */
export interface McpStatus {
  /** Whether the protocol is built into this deployment at all. */
  available: boolean;
  /** Whether it is currently answering requests. */
  enabled: boolean;
  path: string;
  ssePath: string;
}

/**
 * Footer switch for the Model Context Protocol.
 *
 * The protocol is how an agent reaches this camera, so being able to close it
 * without editing an environment variable and restarting the server is the
 * point: someone who wants the camera to stop being reachable wants that now,
 * not after a redeploy.
 *
 * Green means agents can connect, grey means the door is shut. A deployment
 * built without the protocol shows nothing at all, because there is no switch
 * to offer and an inert control would only invite the question.
 *
 * Whoever lacks the permission still sees the state. Knowing whether the camera
 * is reachable is not the same as deciding it, and the first matters to anyone
 * looking at the screen.
 */
@Component({
  selector: 'app-mcp-toggle',
  standalone: true,
  imports: [CommonModule, TranslateModule],
  templateUrl: './mcp-toggle.component.html',
  styleUrl: './mcp-toggle.component.scss',
})
export class McpToggleComponent implements OnInit {
  private readonly http = inject(HttpClient);
  private readonly auth = inject(AuthService);

  private readonly endpoint = `${environment.apiUrl}/${environment.apiVersion}/health/mcp`;

  readonly status = signal<McpStatus | null>(null);
  readonly pending = signal(false);

  /** Set when the server refused a change, cleared on the next attempt. */
  readonly errorMessage = signal<string | null>(null);

  /**
   * Whether this user may open or close the protocol.
   *
   * The switch is server wide: closing it cuts off every connected agent, not
   * just this viewer's, so it sits behind the same permission as the rest of
   * the integration configuration.
   */
  readonly canConfigure = computed(() => this.auth.hasPermission('events:manage'));

  /** Whether there is a protocol in this deployment to show at all. */
  readonly isAvailable = computed(() => this.status()?.available ?? false);

  readonly isEnabled = computed(() => this.status()?.enabled ?? false);

  ngOnInit(): void {
    this.http.get<McpStatus>(this.endpoint).subscribe({
      // A deployment without the protocol is an ordinary configuration, so a
      // failure here hides the control rather than raising an error nobody can
      // act on from the footer.
      next: (status) => this.status.set(status),
      error: () => this.status.set(null),
    });
  }

  /**
   * Open or close the protocol.
   *
   * The server answers with the whole status rather than an acknowledgement, so
   * what is drawn is what the server holds rather than what was asked for.
   */
  toggle(): void {
    if (!this.canConfigure() || !this.isAvailable() || this.pending()) {
      return;
    }

    this.pending.set(true);
    this.errorMessage.set(null);

    this.http
      .put<McpStatus>(this.endpoint, { enabled: !this.isEnabled() })
      .subscribe({
        next: (status) => {
          this.status.set(status);
          this.pending.set(false);
        },
        error: (err) => {
          this.errorMessage.set(err?.error?.detail ?? 'mcpToggle.failed');
          this.pending.set(false);
        },
      });
  }
}
