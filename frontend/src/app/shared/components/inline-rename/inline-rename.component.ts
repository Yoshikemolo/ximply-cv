import {
  Component,
  ElementRef,
  EventEmitter,
  Input,
  Output,
  ViewChild,
  computed,
  input,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { TranslateModule } from '@ngx-translate/core';

/**
 * Reason a proposed name was rejected, or null when it is acceptable.
 */
export type RenameError = 'empty' | 'duplicate' | null;

/**
 * Inline rename control for a catalog entry, an object or a person alike.
 *
 * Reading mode shows the name preceded by a pencil button. Pressing it swaps
 * the text for an input with a clear button on its right; Enter commits and
 * Escape reverts.
 *
 * Validation runs as the user types rather than on submit, so the field turns
 * red the moment the name becomes unusable instead of only when they try to
 * save. Enter is inert while the name is invalid, which makes the rule
 * impossible to bypass by pressing it anyway.
 */
@Component({
  selector: 'app-inline-rename',
  standalone: true,
  imports: [CommonModule, FormsModule, TranslateModule],
  templateUrl: './inline-rename.component.html',
  styleUrl: './inline-rename.component.scss',
})
export class InlineRenameComponent {
  @ViewChild('nameInput') nameInput?: ElementRef<HTMLInputElement>;

  /** The name currently stored for this entry. */
  readonly name = input.required<string>();

  /**
   * Every other name already in use, so a clash is reported while typing
   * instead of after a round trip. The server validates again regardless.
   */
  readonly takenNames = input<string[]>([]);

  /** Disables the pencil, for entries the user may not rename. */
  readonly disabled = input(false);

  /** Extra classes applied to the displayed name. */
  @Input() nameClass = '';

  /** Emits the accepted new name. */
  @Output() renamed = new EventEmitter<string>();

  readonly isEditing = signal(false);
  readonly draft = signal('');
  /** Set from a failed save, so a server side rejection shows in the same place. */
  readonly serverError = signal<string | null>(null);

  /**
   * Why the current draft cannot be saved, or null when it can.
   *
   * The comparison trims and lowercases both sides because two names differing
   * only in case or padding are indistinguishable in a list and would leave the
   * user unable to tell the entries apart.
   */
  readonly error = computed<RenameError>(() => {
    const candidate = this.draft().trim();

    if (!candidate) {
      return 'empty';
    }

    const current = this.name().trim().toLowerCase();
    const proposed = candidate.toLowerCase();

    // Saving an entry under its own name is a no-op, never a clash.
    if (proposed === current) {
      return null;
    }

    const clash = this.takenNames().some(
      (taken) => taken.trim().toLowerCase() === proposed,
    );

    return clash ? 'duplicate' : null;
  });

  readonly isInvalid = computed(() => this.error() !== null);

  readonly errorMessage = computed<string | null>(() => {
    if (this.serverError()) {
      return this.serverError();
    }
    switch (this.error()) {
      case 'empty':
        return 'common.rename.errors.empty';
      case 'duplicate':
        return 'common.rename.errors.duplicate';
      default:
        return null;
    }
  });

  /**
   * Enter edit mode with the current name as the starting draft.
   */
  startEditing(): void {
    if (this.disabled()) {
      return;
    }
    this.draft.set(this.name());
    this.serverError.set(null);
    this.isEditing.set(true);
    // The input only exists after this change is rendered.
    queueMicrotask(() => {
      this.nameInput?.nativeElement.focus();
      this.nameInput?.nativeElement.select();
    });
  }

  /**
   * Leave edit mode, discarding whatever was typed.
   */
  cancelEditing(): void {
    this.isEditing.set(false);
    this.draft.set('');
    this.serverError.set(null);
  }

  /**
   * Empty the field, leaving it in the invalid state so the reason is visible.
   */
  clearDraft(): void {
    this.draft.set('');
    this.serverError.set(null);
    this.nameInput?.nativeElement.focus();
  }

  onDraftChange(value: string): void {
    this.draft.set(value);
    // A rejection from the server describes the value that was sent, so it
    // stops applying the moment the user edits the field again.
    this.serverError.set(null);
  }

  /**
   * Commit the draft when it is valid. Does nothing otherwise.
   */
  submit(): void {
    if (this.isInvalid()) {
      return;
    }
    const accepted = this.draft().trim();
    if (accepted === this.name()) {
      this.cancelEditing();
      return;
    }
    this.renamed.emit(accepted);
    this.isEditing.set(false);
  }

  onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Enter') {
      event.preventDefault();
      event.stopPropagation();
      this.submit();
      return;
    }
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      this.cancelEditing();
    }
  }

  /**
   * Show a rejection that only the server could detect.
   *
   * @param messageKey Translation key describing the failure.
   */
  showServerError(messageKey: string): void {
    this.serverError.set(messageKey);
    this.isEditing.set(true);
    queueMicrotask(() => this.nameInput?.nativeElement.focus());
  }
}
