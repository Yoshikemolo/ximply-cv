import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { TranslateModule } from '@ngx-translate/core';
import { environment } from '@env';

/** One inference backend and whether it runs on dedicated hardware. */
export interface AccelerationBackend {
  name: string;
  accelerated: boolean;
  device: string;
  detail: string;
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
 * Badge reporting whether detection is running on dedicated hardware.
 *
 * Shown only when there is something to report. On a machine without an
 * accelerator the badge stays out of the way entirely rather than announcing an
 * absence, which is the normal case and not news.
 *
 * Hovering reveals which backends are actually accelerated, because they can
 * differ: object detection can be on the GPU while face recognition is not,
 * and a single green light over that would be misleading.
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

  readonly status = signal<AccelerationStatus | null>(null);
  readonly showDetails = signal(false);

  ngOnInit(): void {
    this.http
      .get<AccelerationStatus>(
        `${environment.apiUrl}/${environment.apiVersion}/health/acceleration`,
      )
      .subscribe({
        next: (status) => this.status.set(status),
        // A machine with no accelerator is the ordinary case, so a failure here
        // hides the badge rather than surfacing an error the user cannot act on.
        error: () => this.status.set(null),
      });
  }

  /** Memory in whole gigabytes, which is how a GPU is normally described. */
  memoryGb(): number | null {
    const mb = this.status()?.deviceMemoryMb;
    return mb ? Math.round(mb / 1024) : null;
  }

  /** How many backends are actually accelerated, out of the total. */
  acceleratedCount(): number {
    return this.status()?.backends.filter((b) => b.accelerated).length ?? 0;
  }

  totalCount(): number {
    return this.status()?.backends.length ?? 0;
  }

  /** True when the accelerator is present but not every backend uses it. */
  isPartial(): boolean {
    const total = this.totalCount();
    return total > 0 && this.acceleratedCount() > 0 && this.acceleratedCount() < total;
  }

  toggleDetails(): void {
    this.showDetails.set(!this.showDetails());
  }
}
