import {
  Component,
  computed,
  inject,
  input,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { TranslateModule } from '@ngx-translate/core';
import hljs from 'highlight.js/lib/core';
import bash from 'highlight.js/lib/languages/bash';
import csharp from 'highlight.js/lib/languages/csharp';
import java from 'highlight.js/lib/languages/java';
import javascript from 'highlight.js/lib/languages/javascript';
import json from 'highlight.js/lib/languages/json';
import python from 'highlight.js/lib/languages/python';
import typescript from 'highlight.js/lib/languages/typescript';
import xml from 'highlight.js/lib/languages/xml';

// Registered once for the whole application. Only the languages actually shown
// are imported: the full library is several hundred kilobytes of grammars for
// languages this project never displays.
let registered = false;

function registerLanguages(): void {
  if (registered) {
    return;
  }
  hljs.registerLanguage('bash', bash);
  hljs.registerLanguage('csharp', csharp);
  hljs.registerLanguage('java', java);
  hljs.registerLanguage('javascript', javascript);
  hljs.registerLanguage('json', json);
  hljs.registerLanguage('python', python);
  hljs.registerLanguage('typescript', typescript);
  // JSX inside a JavaScript example is highlighted through the xml grammar.
  hljs.registerLanguage('xml', xml);
  registered = true;
}

/**
 * A code block with syntax colouring and a copy button.
 *
 * The text stays selectable, unlike the rest of the interface: a snippet exists
 * to be taken away, and someone who wants only three lines of it should not be
 * forced to copy the whole thing.
 *
 * Highlighting happens once per input rather than on every change detection
 * pass, because it walks the source and builds markup, which is not something
 * to repeat for a block that has not changed.
 */
@Component({
  selector: 'app-code-snippet',
  standalone: true,
  imports: [CommonModule, TranslateModule],
  templateUrl: './code-snippet.component.html',
  styleUrl: './code-snippet.component.scss',
})
export class CodeSnippetComponent {
  private readonly sanitizer = inject(DomSanitizer);

  /** The source to display. */
  readonly code = input.required<string>();

  /** Language for the grammar, matching the names registered above. */
  readonly language = input<string>('bash');

  /** Optional caption shown beside the copy button, such as a file name. */
  readonly caption = input<string>('');

  readonly copied = signal(false);

  /**
   * The highlighted markup.
   *
   * Trusted because it is produced by the highlighter from source this
   * application supplies, never from anything a user typed. If that ever stops
   * being true, this is the line that has to change.
   */
  readonly highlighted = computed<SafeHtml>(() => {
    registerLanguages();
    const source = this.code();
    const language = this.language();

    try {
      const result = hljs.getLanguage(language)
        ? hljs.highlight(source, { language, ignoreIllegals: true })
        : hljs.highlightAuto(source);
      return this.sanitizer.bypassSecurityTrustHtml(result.value);
    } catch {
      // A grammar that fails should show the code, not an empty box.
      return this.sanitizer.bypassSecurityTrustHtml(this.escape(source));
    }
  });

  private escape(value: string): string {
    return value
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  /**
   * Put the snippet on the clipboard and confirm it briefly.
   *
   * Falls back to a hidden textarea where the clipboard API is unavailable,
   * which is the case on any origin the browser does not consider secure.
   */
  async copy(): Promise<void> {
    const source = this.code();

    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(source);
      } else {
        const area = document.createElement('textarea');
        area.value = source;
        area.style.position = 'fixed';
        area.style.opacity = '0';
        document.body.appendChild(area);
        area.select();
        document.execCommand('copy');
        document.body.removeChild(area);
      }

      this.copied.set(true);
      setTimeout(() => this.copied.set(false), 2000);
    } catch {
      this.copied.set(false);
    }
  }
}
