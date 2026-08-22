import {
  Component,
  ElementRef,
  HostListener,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { TranslateModule } from '@ngx-translate/core';
import { AuthService } from '@core/services/auth.service';
import { environment } from '@env';

/** One inference backend, what it could use and what it was asked to use. */
export interface AccelerationBackend {
  key: string;
  name: string;
  accelerated: boolean;
  device: string;
  detail: string;
  supported: boolean;
  enabled: boolean;
}

/** What the server reports about its own hardware. */
export interface AccelerationStatus {
  available: boolean;
  active: boolean;
  deviceName?: string;
  deviceMemoryMb?: number;
  driver?: string;
  computeCapability?: string;
  backends: AccelerationBackend[];
}

/**
 * Badge reporting whether inference is running on dedicated hardware, and the
 * panel that decides it.
 *
 * Green means dedicated hardware is doing the work, amber means the processor
 * is. The colour answers the only question the badge exists to answer, so it is
 * never spent on anything else.
 *
 * The badge opens rather than only explaining, because the three backends move
 * independently: object detection can be on the accelerator while the landmark
 * models are not, and someone who wants to change that should not have to find
 * an environment variable and restart the server. The panel is where the detail
 * that used to be a tooltip now lives, next to the switch that acts on it.
 *
 * A backend the machine cannot accelerate is shown with its switch disabled and
 * the reason beside it. Hiding it would leave the panel looking complete while
 * silently omitting the row that explains why the badge is amber.
 */
@Component({
  selector: 'app-acceleration-badge',
  standalone: true,
  imports: [CommonModule, TranslateModule],
  templateUrl: './acceleration-badge.component.html',
  styleUrl: './acceleration-badge.component.scss',
})
export class AccelerationBadgeComponent implements OnInit {
  private readonly http = inject(HttpClient);
  private readonly auth = inject(AuthService);
  private readonly host = inject(ElementRef<HTMLElement>);

  private readonly endpoint = `${environment.apiUrl}/${environment.apiVersion}/health/acceleration`;

  readonly status = signal<AccelerationStatus | null>(null);
  readonly isOpen = signal(false);

  /** The backend currently being switched, so only its row shows the wait. */
  readonly pending = signal<string | null>(null);

  /** Set when the server refused a change, cleared on the next attempt. */
  readonly errorMessage = signal<string | null>(null);

  /**
   * Whether this user may move work between devices.
   *
   * The setting is server wide: it changes what every viewer's frames run on,
   * not just this one's. Someone without the permission still sees the panel,
   * because knowing what the server is doing is not the same as deciding it.
   */
  readonly canConfigure = computed(() =>
    this.auth.hasPermission('detection:configure'),
  );

  /** Memory in whole gigabytes, which is how a GPU is normally described. */
  readonly memoryGb = computed(() => {
    const mb = this.status()?.deviceMemoryMb;
    return mb ? Math.round(mb / 1024) : null;
  });

  /** How many backends are actually accelerated, out of the total. */
  readonly acceleratedCount = computed(
    () => this.status()?.backends.filter((b) => b.accelerated).length ?? 0,
  );

  readonly totalCount = computed(() => this.status()?.backends.length ?? 0);

  /** Whether the machine has an accelerator at all, which decides the toggles. */
  readonly hasHardware = computed(() => this.status()?.available ?? false);

  ngOnInit(): void {
    this.http.get<AccelerationStatus>(this.endpoint).subscribe({
      next: (status) => this.status.set(status),
      // A machine with no accelerator is the ordinary case, so a failure here
      // hides the badge rather than surfacing an error the user cannot act on.
      error: () => this.status.set(null),
    });
  }

  toggleOpen(): void {
    this.isOpen.update((open) => !open);
    if (!this.isOpen()) {
      this.errorMessage.set(null);
    }
  }

  close(): void {
    this.isOpen.set(false);
    this.errorMessage.set(null);
  }

  /** Close on a click anywhere else, which is what a panel like this should do. */
  @HostListener('document:click', ['$event'])
  onDocumentClick(event: MouseEvent): void {
    if (this.isOpen() && !this.host.nativeElement.contains(event.target as Node)) {
      this.close();
    }
  }

  @HostListener('document:keydown.escape')
  onEscape(): void {
    this.close();
  }

  /**
   * Move one backend on or off the accelerator.
   *
   * The server answers with the whole status rather than an acknowledgement, so
   * what is drawn is what the server holds. A switch that flipped optimistically
   * and then had to flip back would be worse than a short wait, because the
   * models behind it really do take a moment to rebuild.
   */
  setBackend(backend: AccelerationBackend, enabled: boolean): void {
    if (!this.canConfigure() || !backend.supported || this.pending()) {
      return;
    }

    this.pending.set(backend.key);
    this.errorMessage.set(null);

    this.http
      .put<AccelerationStatus>(this.endpoint, { backend: backend.key, enabled })
      .subscribe({
        next: (status) => {
          this.status.set(status);
          this.pending.set(null);
        },
        error: (err) => {
          this.errorMessage.set(err?.error?.detail ?? 'acceleration.failed');
          this.pending.set(null);
        },
      });
  }
}
