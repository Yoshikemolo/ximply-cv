import { Component, OnInit, OnDestroy, inject, signal, computed, ElementRef, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { TranslateModule } from '@ngx-translate/core';
import { DetectionService, DetectionResult, BarcodeResult, CaptureDetectionRequest, SkeletonResult } from '@core/services/detection.service';
import { ObjectsService, CatalogObject } from '@core/services/objects.service';
import { InlineRenameComponent } from '@shared/components/inline-rename/inline-rename.component';
import { AccelerationBadgeComponent } from '@shared/components/acceleration-badge/acceleration-badge.component';
import { Subscription } from 'rxjs';

/**
 * A detection is only reported as a fact above this confidence. Below it the
 * label is prefixed with "Possible", because announcing a guess as a certainty
 * is worse than admitting the doubt.
 */
const CERTAINTY_THRESHOLD = 0.7;

/** A card with no fresh sighting for this long is dropped from the list. */
const CARD_TTL_MS = 4000;

/** Pixel width of the thumbnail kept for each card. */
const THUMBNAIL_WIDTH = 96;

/** Colour per skeleton part, so the hierarchy reads at a glance. */
const SKELETON_COLORS: Record<string, string> = {
  head: '#f472b6',
  torso: '#38bdf8',
  left_arm: '#4ade80',
  right_arm: '#22d3ee',
  left_leg: '#facc15',
  right_leg: '#fb923c',
  thumb: '#f87171',
  index: '#fbbf24',
  middle: '#34d399',
  ring: '#60a5fa',
  pinky: '#c084fc',
  palm: '#e2e8f0',
  mesh: 'rgba(226, 232, 240, 0.35)',
  face_oval: '#f8fafc',
  left_eye: '#38bdf8',
  right_eye: '#38bdf8',
  left_eyebrow: '#a78bfa',
  right_eyebrow: '#a78bfa',
  left_iris: '#22d3ee',
  right_iris: '#22d3ee',
  lips: '#fb7185',
  nose: '#fbbf24',
};

// Color palette for different detection classes
const DETECTION_COLORS = [
  '#22c55e', '#3b82f6', '#f59e0b', '#ef4444', '#8b5cf6',
  '#ec4899', '#06b6d4', '#84cc16', '#f97316', '#6366f1',
];

@Component({
  selector: 'app-view-page',
  standalone: true,
  imports: [CommonModule, FormsModule, TranslateModule, InlineRenameComponent, AccelerationBadgeComponent],
  templateUrl: './view-page.component.html',
  styleUrl: './view-page.component.scss',
})
export class ViewPageComponent implements OnInit, OnDestroy {
  @ViewChild('videoElement') videoElement!: ElementRef<HTMLVideoElement>;
  @ViewChild('canvasElement') canvasElement!: ElementRef<HTMLCanvasElement>;

  private readonly detectionService = inject(DetectionService);
  private readonly objectsService = inject(ObjectsService);

  isStreaming = signal(false);
  isLoading = signal(false);
  detections = signal<Detection[]>([]);
  barcodes = signal<Barcode[]>([]);
  selectedCamera = signal<string>('');
  availableCameras = signal<MediaDeviceInfo[]>([]);
  errorMessage = signal<string | null>(null);
  confidenceThreshold = signal(0.3);
  fps = signal(0);

  // Toggle to show only custom (matched) objects
  showOnlyCustomObjects = signal(false);
  isRefreshingFeatures = signal(false);

  // Toggle to hide person detections (useful when holding objects)
  hidePersonDetections = signal(true);

  /**
   * Whether the body and hand wireframes are extracted and drawn.
   *
   * The flag travels to the server rather than only filtering on arrival: the
   * landmark models are the expensive part of a frame, so switching the overlay
   * off should stop the work, not just hide its result.
   */
  showSkeletons = signal(true);

  /** Whether the facial feature mesh is extracted and drawn. */
  showFaceMesh = signal(true);

  /**
   * Which model draws the shape of a detection.
   *
   * "yolo" draws the bounding box the detector produced. "sam" prompts Segment
   * Anything with that same box and draws the real outline instead. It is never
   * a replacement for detection: Segment Anything has no idea what it is
   * looking at, so labels, catalog matches and person identities keep coming
   * from the detector either way.
   */
  detectionModel = signal<'yolo' | 'sam'>('yolo');

  /**
   * How narrow a silhouette to accept, from 0 for the widest to 1 for the
   * narrowest.
   *
   * A box prompt is ambiguous: the rectangle around a person also contains the
   * chair behind them, and the segmenter offers several readings of it. This
   * chooses among them, which is what stops a silhouette swallowing whatever
   * the subject is sitting on.
   */
  segmentationTightness = signal(0.5);

  /**
   * Whether other detections inside a box are marked as background.
   *
   * The detector has already found the chair and the table separately, so their
   * positions are known and can be fed back to say what the subject is not.
   */
  segmentationExcludeSiblings = signal(true);

  // Filtered detections based on toggles
  filteredDetections = computed(() => {
    let result = this.detections();

    // Filter out person detections if toggle is enabled
    if (this.hidePersonDetections()) {
      result = result.filter(d => d.label.toLowerCase() !== 'person');
    }

    // Only show custom objects if toggle is enabled
    if (this.showOnlyCustomObjects()) {
      result = result.filter(d => d.objectId);
    }

    return result;
  });

  // Skeleton wireframes for people and hands
  skeletons = signal<SkeletonResult[]>([]);

  /**
   * Which of the two panels is open.
   *
   * Only one is expanded at a time: the column is not tall enough for both, and
   * the whole point of expanding the detections list is to give it the room the
   * controls were using.
   */
  expandedPanel = signal<'controls' | 'detections'>('controls');

  controlsCollapsed = computed(() => this.expandedPanel() !== 'controls');
  detectionsExpanded = computed(() => this.expandedPanel() === 'detections');

  /** Free text applied to the name, the type and the percentage of a card. */
  detectionQuery = signal('');

  /**
   * Which slice of the detections the list is showing.
   *
   * "threshold" is the one that earns its place: below the certainty threshold
   * a detection is a guess, and being able to hide the guesses in one click is
   * the difference between a readable list and a wall of maybes.
   */
  detectionTab = signal<DetectionTab>('all');

  readonly detectionTabs: DetectionTab[] = ['all', 'threshold', 'humans', 'objects'];

  /**
   * Aggregated detections, one card per distinct thing.
   *
   * Detection runs several times a second, so the raw list flickers: the same
   * object reappears every frame with a slightly different confidence. Cards
   * collapse that stream into one entry per thing, holding on to the best
   * sighting seen recently rather than the most recent one, so the list stays
   * readable and the thumbnail shows the clearest view rather than a blurred
   * frame.
   */
  detectionCards = signal<DetectionCard[]>([]);

  /**
   * Cards left after the search box and the type filter.
   *
   * The query is matched against the name, the translated type and the
   * confidence as a whole number, so typing "85" finds everything detected at
   * eighty five percent and typing "human" finds the people.
   */
  visibleDetectionCards = computed(() => {
    const query = this.detectionQuery().trim().toLowerCase();
    const tab = this.detectionTab();

    return this.detectionCards().filter((card) => {
      if (!this.matchesTab(card, tab)) {
        return false;
      }

      if (!query) {
        return true;
      }

      const percentage = String(Math.round(card.confidence * 100));
      const haystack = [
        card.objectName ?? '',
        card.label,
        this.cardType(card),
        percentage,
        `${percentage}%`,
      ]
        .join(' ')
        .toLowerCase();

      return haystack.includes(query);
    });
  });

  /** Names already in use, so a rename clash is caught before it is sent. */
  takenNames = computed(() => this.catalogObjects().map((obj) => obj.name));

  // Capture modal state
  showCaptureModal = signal(false);
  selectedDetection = signal<Detection | null>(null);
  captureObjectName = signal('');
  captureObjectDescription = signal('');
  isSaving = signal(false);
  lastFrameBase64 = signal<string>('');

  // Catalog objects for autocomplete
  catalogObjects = signal<CatalogObject[]>([]);

  // Computed: check if name matches an existing object
  matchingObject = computed(() => {
    const name = this.captureObjectName().trim().toLowerCase();
    if (!name) return null;
    return this.catalogObjects().find(obj => obj.name.toLowerCase() === name) || null;
  });

  // Computed: filtered suggestions based on current input
  nameSuggestions = computed(() => {
    const query = this.captureObjectName().trim().toLowerCase();
    if (!query) return [];
    return this.catalogObjects()
      .filter(obj => obj.name.toLowerCase().includes(query))
      .map(obj => obj.name)
      .slice(0, 5);
  });

  /** Last edge list seen per skeleton kind, since the server sends them once. */
  private edgeCache = new Map<string, SkeletonResult['edges']>();

  private mediaStream: MediaStream | null = null;
  private animationFrameId: number | null = null;
  private detectionInterval: ReturnType<typeof setInterval> | null = null;
  private lastFrameTime = 0;
  private frameCount = 0;
  private isDetecting = false;
  private currentSubscription: Subscription | null = null;

  async ngOnInit(): Promise<void> {
    await this.loadCameras();
    this.loadCatalogObjects();
  }

  private loadCatalogObjects(): void {
    this.objectsService.getObjects({ page_size: 100 }).subscribe({
      next: (response) => {
        this.catalogObjects.set(response.items);
      },
      error: (err) => {
        console.warn('Could not load catalog objects for autocomplete:', err);
      },
    });
  }

  ngOnDestroy(): void {
    this.stopStream();
  }

  private async loadCameras(): Promise<void> {
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      const videoDevices = devices.filter(d => d.kind === 'videoinput');
      this.availableCameras.set(videoDevices);

      if (videoDevices.length > 0) {
        this.selectedCamera.set(videoDevices[0].deviceId);
      }
    } catch (error) {
      this.errorMessage.set('view.errors.cameraPermission');
    }
  }

  async startStream(): Promise<void> {
    if (this.isStreaming()) return;

    this.isLoading.set(true);
    this.errorMessage.set(null);

    try {
      // Load catalog features for custom object recognition BEFORE starting detection
      try {
        const catalogResponse = await this.detectionService.loadCatalogFeatures().toPromise();
        if (catalogResponse) {
          console.log(
            `Loaded ${catalogResponse.objectsLoaded}/${catalogResponse.totalObjects} catalog objects for recognition`
          );
          if (catalogResponse.objectsFailed && catalogResponse.objectsFailed > 0) {
            console.warn(`${catalogResponse.objectsFailed} objects failed to load features`);
          }
        }
      } catch (err) {
        console.warn('Could not load catalog features:', err);
        // Continue anyway - YOLO detection will still work
      }

      const constraints: MediaStreamConstraints = {
        video: {
          deviceId: this.selectedCamera() ? { exact: this.selectedCamera() } : undefined,
          width: { ideal: 1280 },
          height: { ideal: 720 },
          frameRate: { ideal: 30 },
        },
      };

      this.mediaStream = await navigator.mediaDevices.getUserMedia(constraints);

      if (this.videoElement?.nativeElement) {
        this.videoElement.nativeElement.srcObject = this.mediaStream;
        await this.videoElement.nativeElement.play();
        this.isStreaming.set(true);
        this.startDetectionLoop();
      }
    } catch (error: any) {
      this.errorMessage.set('view.errors.streamFailed');
    } finally {
      this.isLoading.set(false);
    }
  }

  stopStream(): void {
    if (this.animationFrameId) {
      cancelAnimationFrame(this.animationFrameId);
      this.animationFrameId = null;
    }

    if (this.detectionInterval) {
      clearInterval(this.detectionInterval);
      this.detectionInterval = null;
    }

    if (this.currentSubscription) {
      this.currentSubscription.unsubscribe();
      this.currentSubscription = null;
    }

    if (this.mediaStream) {
      this.mediaStream.getTracks().forEach(track => track.stop());
      this.mediaStream = null;
    }

    if (this.videoElement?.nativeElement) {
      this.videoElement.nativeElement.srcObject = null;
    }

    this.isStreaming.set(false);
    this.detections.set([]);
    this.detectionCards.set([]);
    this.skeletons.set([]);
    this.fps.set(0);
    this.isDetecting = false;
  }

  onCameraChange(event: Event): void {
    const select = event.target as HTMLSelectElement;
    this.selectedCamera.set(select.value);

    if (this.isStreaming()) {
      this.stopStream();
      this.startStream();
    }
  }

  onThresholdChange(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.confidenceThreshold.set(parseFloat(input.value));
  }

  toggleCustomObjectsOnly(): void {
    const newValue = !this.showOnlyCustomObjects();
    this.showOnlyCustomObjects.set(newValue);

    // When enabling custom-only mode, refresh the feature cache
    if (newValue) {
      this.refreshFeatureCache();
    }
  }

  togglePersonDetections(): void {
    this.hidePersonDetections.set(!this.hidePersonDetections());
  }

  toggleSkeletons(): void {
    this.showSkeletons.set(!this.showSkeletons());
    if (!this.showSkeletons()) {
      this.skeletons.update((all) => all.filter((s) => s.kind === 'face'));
    }
  }

  /**
   * Switch between drawing boxes and drawing silhouettes.
   *
   * @param model The model that shapes each detection.
   */
  setDetectionModel(model: 'yolo' | 'sam'): void {
    this.detectionModel.set(model);
  }

  onTightnessChange(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.segmentationTightness.set(parseFloat(input.value));
  }

  toggleExcludeSiblings(): void {
    this.segmentationExcludeSiblings.set(!this.segmentationExcludeSiblings());
  }

  toggleFaceMesh(): void {
    this.showFaceMesh.set(!this.showFaceMesh());
    if (!this.showFaceMesh()) {
      this.skeletons.update((all) => all.filter((s) => s.kind !== 'face'));
    }
  }

  private refreshFeatureCache(): void {
    this.isRefreshingFeatures.set(true);

    this.detectionService.loadCatalogFeatures().subscribe({
      next: (response) => {
        console.log(`Feature cache refreshed: ${response.objectsLoaded} objects loaded`);
        this.isRefreshingFeatures.set(false);
      },
      error: (err) => {
        console.error('Failed to refresh feature cache:', err);
        this.isRefreshingFeatures.set(false);
      },
    });
  }

  private startDetectionLoop(): void {
    // Start rendering loop for drawing
    const renderFrame = (timestamp: number): void => {
      if (!this.isStreaming()) return;

      // Calculate FPS
      this.frameCount++;
      if (timestamp - this.lastFrameTime >= 1000) {
        this.fps.set(this.frameCount);
        this.frameCount = 0;
        this.lastFrameTime = timestamp;
      }

      // Draw video and detections
      this.renderDetections();

      this.animationFrameId = requestAnimationFrame(renderFrame);
    };

    this.animationFrameId = requestAnimationFrame(renderFrame);

    // Start detection interval (send frames to backend every 200ms)
    this.detectionInterval = setInterval(() => {
      this.sendFrameForDetection();
    }, 200);
  }

  private sendFrameForDetection(): void {
    if (this.isDetecting || !this.isStreaming()) return;

    const video = this.videoElement?.nativeElement;
    if (!video || video.videoWidth === 0) return;

    this.isDetecting = true;

    try {
      // Capture frame from video
      const imageBase64 = this.detectionService.captureFrame(video, 0.7);

      // Send to backend for detection
      this.currentSubscription = this.detectionService
        .detect(imageBase64, this.confidenceThreshold(), {
          hidePersonDetections: this.hidePersonDetections(),
          showOnlyCustomObjects: this.showOnlyCustomObjects(),
          includeSkeletons: this.showSkeletons(),
          includeFaceMesh: this.showFaceMesh(),
          detectionModel: this.detectionModel(),
          segmentationTightness: this.segmentationTightness(),
          segmentationExcludeSiblings: this.segmentationExcludeSiblings(),
        })
        .subscribe({
          next: (response) => {
            // Convert response to local Detection format with colors
            const newDetections: Detection[] = response.detections.map((d, i) => ({
              id: `${d.label}-${i}-${Date.now()}`,
              label: d.objectName || d.label,
              confidence: d.confidence,
              bbox: d.bbox,
              color: DETECTION_COLORS[d.classId ? d.classId % DETECTION_COLORS.length : i % DETECTION_COLORS.length],
              objectId: d.objectId,
              objectName: d.objectName,
              matchConfidence: d.matchConfidence,
              polygon: d.polygon,
            }));
            this.detections.set(newDetections);
            this.mergeDetectionCards(newDetections, video);
            this.skeletons.set(this.withCachedEdges(response.skeletons ?? []));

            // Convert barcodes
            const newBarcodes: Barcode[] = (response.barcodes || []).map((b, i) => ({
              id: `barcode-${i}-${Date.now()}`,
              type: b.barcodeType,
              data: b.data,
              bbox: b.bbox,
              quality: b.quality,
            }));
            this.barcodes.set(newBarcodes);

            this.isDetecting = false;
          },
          error: (err) => {
            console.error('Detection error:', err);
            this.isDetecting = false;
          },
        });
    } catch (error) {
      console.error('Failed to capture frame:', error);
      this.isDetecting = false;
    }
  }

  /**
   * Open one panel, which closes the other.
   *
   * @param panel The panel to expand.
   */
  expandPanel(panel: 'controls' | 'detections'): void {
    this.expandedPanel.set(panel);
  }

  /**
   * Toggle a panel: expanding it collapses the other one.
   *
   * @param panel The panel the user acted on.
   */
  togglePanel(panel: 'controls' | 'detections'): void {
    this.expandedPanel.set(
      this.expandedPanel() === panel ? (panel === 'controls' ? 'detections' : 'controls') : panel,
    );
  }

  /**
   * Classify a card for the type filter.
   *
   * - "known": recognised as something in this catalog, with confidence.
   * - "human": a person, whether or not they have been identified yet.
   * - "unknown": a class the detector knows but this catalog does not.
   * - "other": anything that fits none of the above, such as a barcode target.
   *
   * @param card The card to classify.
   * @returns The type used by the filter and shown as a badge.
   */
  cardType(card: DetectionCard): DetectionCardType {
    const label = (card.objectName ?? card.label).toLowerCase();
    const rawLabel = card.label.toLowerCase();

    if (rawLabel === 'person' || label.startsWith('person ')) {
      return 'human';
    }
    if (card.objectId) {
      return 'known';
    }
    if (rawLabel) {
      return 'unknown';
    }
    return 'other';
  }

  /**
   * Translation key for the badge of a card type.
   */
  cardTypeLabel(type: DetectionCardType): string {
    return `view.detections.types.${type}`;
  }

  /**
   * Whether a card belongs in the selected tab.
   *
   * @param card The card under consideration.
   * @param tab The tab currently selected.
   */
  matchesTab(card: DetectionCard, tab: DetectionTab): boolean {
    switch (tab) {
      case 'threshold':
        return this.cardCertainty(card) >= CERTAINTY_THRESHOLD;
      case 'humans':
        return this.cardType(card) === 'human';
      case 'objects':
        return this.cardType(card) !== 'human';
      default:
        return true;
    }
  }

  /** Translation key for a tab label. */
  tabLabel(tab: DetectionTab): string {
    return `view.detections.tabs.${tab}`;
  }

  /** How many cards the given tab would show, for its counter. */
  tabCount(tab: DetectionTab): number {
    return this.detectionCards().filter((card) => this.matchesTab(card, tab)).length;
  }

  selectTab(tab: DetectionTab): void {
    this.detectionTab.set(tab);
  }

  onDetectionQueryChange(value: string): void {
    this.detectionQuery.set(value);
  }



  /**
   * Fold this frame's detections into the card list.
   *
   * Cards are keyed by identity when the thing was recognised and by label
   * otherwise, so ten frames of the same bottle stay one card. A card only
   * takes the new confidence and thumbnail when this sighting is better than
   * the one already stored, which is what makes the list settle on the
   * clearest view instead of whatever the last frame happened to catch.
   *
   * @param detections Detections from the current frame.
   * @param video The video element the frame came from, used for thumbnails.
   */
  private mergeDetectionCards(detections: Detection[], video: HTMLVideoElement | null): void {
    const now = Date.now();
    const byKey = new Map<string, DetectionCard>();

    for (const card of this.detectionCards()) {
      byKey.set(card.key, card);
    }

    for (const detection of detections) {
      const key = detection.objectId ?? detection.label.toLowerCase();
      const existing = byKey.get(key);

      if (!existing) {
        byKey.set(key, {
          key,
          label: detection.label,
          objectId: detection.objectId,
          objectName: detection.objectName,
          confidence: detection.confidence,
          matchConfidence: detection.matchConfidence,
          color: detection.color,
          bbox: detection.bbox,
          thumbnail: this.cropThumbnail(video, detection.bbox),
          lastSeen: now,
          sightings: 1,
        });
        continue;
      }

      existing.lastSeen = now;
      existing.sightings += 1;
      existing.objectId = detection.objectId ?? existing.objectId;
      existing.objectName = detection.objectName ?? existing.objectName;

      if (detection.confidence > existing.confidence) {
        existing.confidence = detection.confidence;
        existing.matchConfidence = detection.matchConfidence;
        existing.label = detection.label;
        existing.bbox = detection.bbox;
        existing.color = detection.color;
        const thumbnail = this.cropThumbnail(video, detection.bbox);
        if (thumbnail) {
          existing.thumbnail = thumbnail;
        }
      }
    }

    const alive = Array.from(byKey.values())
      .filter((card) => now - card.lastSeen <= CARD_TTL_MS)
      .sort((a, b) => b.confidence - a.confidence);

    this.detectionCards.set(alive);
  }

  /**
   * Cut the detected region out of the current frame as a small data URL.
   *
   * @param video Source video element.
   * @param bbox Region to crop, in frame coordinates.
   * @returns A data URL, or null when the frame cannot be read.
   */
  private cropThumbnail(
    video: HTMLVideoElement | null,
    bbox: { x: number; y: number; width: number; height: number },
  ): string | null {
    if (!video || video.videoWidth === 0 || bbox.width <= 0 || bbox.height <= 0) {
      return null;
    }

    try {
      const scale = THUMBNAIL_WIDTH / bbox.width;
      const canvas = document.createElement('canvas');
      canvas.width = THUMBNAIL_WIDTH;
      canvas.height = Math.max(1, Math.round(bbox.height * scale));

      const ctx = canvas.getContext('2d');
      if (!ctx) {
        return null;
      }

      // Clamp to the frame so a box running off the edge still crops.
      const sx = Math.max(0, Math.min(bbox.x, video.videoWidth - 1));
      const sy = Math.max(0, Math.min(bbox.y, video.videoHeight - 1));
      const sw = Math.max(1, Math.min(bbox.width, video.videoWidth - sx));
      const sh = Math.max(1, Math.min(bbox.height, video.videoHeight - sy));

      ctx.drawImage(video, sx, sy, sw, sh, 0, 0, canvas.width, canvas.height);
      return canvas.toDataURL('image/jpeg', 0.7);
    } catch {
      return null;
    }
  }

  /**
   * How a card should be labelled on screen.
   *
   * A recognised entry above the certainty threshold is stated plainly. Anything
   * else is a guess and is written as one, whether because the model is unsure
   * or because the thing is only a generic class from the detector rather than
   * something in this catalog.
   *
   * @param card The card to label.
   * @returns The text shown next to the thumbnail.
   */
  cardDisplayLabel(card: DetectionCard): string {
    const name = card.objectName ?? card.label;
    const certainty = this.cardCertainty(card);
    const percentage = Math.round(certainty * 100);

    if (certainty >= CERTAINTY_THRESHOLD && card.objectId) {
      return name;
    }

    return `Possible: ${name} ${percentage}%`;
  }

  /**
   * The number that should be shown next to a card.
   *
   * For a recognised entry this is how sure the matcher is of the identity, not
   * how sure the detector is that something is there. Those diverge badly: a
   * bus detected at 92% matching a phone at 4% must read as 4%, otherwise the
   * interface states a wrong identity with high confidence.
   */
  cardCertainty(card: DetectionCard): number {
    if (card.objectId && card.matchConfidence !== undefined) {
      return card.matchConfidence;
    }
    return card.confidence;
  }

  /**
   * Whether a card is a guess rather than a confirmed identification.
   */
  isUncertain(card: DetectionCard): boolean {
    return this.cardCertainty(card) < CERTAINTY_THRESHOLD || !card.objectId;
  }

  /**
   * Persist a new name for the catalog entry behind a card.
   *
   * Only entries that exist in the catalog can be renamed, so a card that was
   * never recognised is left alone rather than silently creating something.
   *
   * @param card The card whose entry is renamed.
   * @param name The new name, already validated by the control.
   */
  renameCard(card: DetectionCard, name: string): void {
    if (!card.objectId) {
      return;
    }

    this.objectsService.renameObject(card.objectId, name).subscribe({
      next: (updated) => {
        this.detectionCards.update((cards) =>
          cards.map((entry) =>
            entry.key === card.key ? { ...entry, objectName: updated.name } : entry,
          ),
        );
        this.loadCatalogObjects();
      },
      error: (err) => {
        console.error('Rename failed:', err);
        this.errorMessage.set(
          err?.status === 409 ? 'common.rename.errors.duplicate' : 'view.errors.renameFailed',
        );
      },
    });
  }

  /**
   * Open the capture modal for an aggregated card.
   *
   * The card holds the best sighting rather than the newest one, so saving from
   * here stores the clearest crop of the thing instead of whatever the last
   * frame caught.
   *
   * @param card The card to save to the catalog.
   */
  openCaptureModalFromCard(card: DetectionCard): void {
    this.openCaptureModal({
      id: card.key,
      label: card.objectName ?? card.label,
      confidence: card.confidence,
      bbox: card.bbox,
      color: card.color,
      objectId: card.objectId,
      objectName: card.objectName,
    });
  }

  private renderDetections(): void {
    const canvas = this.canvasElement?.nativeElement;
    const video = this.videoElement?.nativeElement;

    if (!canvas || !video) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;

    // Draw video frame
    ctx.drawImage(video, 0, 0);

    // Draw detections
    this.drawDetections(ctx);

    // Draw barcodes
    this.drawBarcodes(ctx);

    // Draw the wireframes last so joints stay readable over the boxes
    this.drawSkeletons(ctx);
  }

  /**
   * Draw every skeleton over the frame.
   *
   * Bones are drawn before joints so the dots sit on top of the lines, and each
   * bone takes the colour of the part it belongs to, which is what makes the
   * hierarchy readable rather than a tangle of identical strokes. An edge whose
   * endpoints are not both visible is skipped instead of being drawn to the
   * origin, which is where an unscored keypoint sits.
   *
   * @param ctx Canvas context of the video overlay.
   */
  /**
   * Fill in the edge lists the server left out.
   *
   * Edges never change for a given kind and the face mesh alone runs to a few
   * thousand of them, so they arrive on the first skeleton of each kind and are
   * remembered here for the rest.
   *
   * @param skeletons Skeletons as they arrived.
   * @returns The same skeletons, each with a usable edge list.
   */
  private withCachedEdges(skeletons: SkeletonResult[]): SkeletonResult[] {
    return skeletons.map((skeleton) => {
      if (skeleton.edges?.length) {
        this.edgeCache.set(skeleton.kind, skeleton.edges);
        return skeleton;
      }
      return { ...skeleton, edges: this.edgeCache.get(skeleton.kind) ?? [] };
    });
  }

  private drawSkeletons(ctx: CanvasRenderingContext2D): void {
    for (const skeleton of this.skeletons()) {
      const points = skeleton.keypoints;
      const isFace = skeleton.kind === 'face';
      const isHand = skeleton.kind === 'hand';

      ctx.lineCap = 'round';
      // The face mesh is thousands of short edges: drawn at body thickness it
      // becomes a solid blob, so it needs a hairline and some transparency.
      ctx.lineWidth = isFace ? 0.6 : isHand ? 2 : 3;

      for (const edge of skeleton.edges) {
        const from = points[edge.from];
        const to = points[edge.to];
        if (!from || !to || from.score <= 0 || to.score <= 0) {
          continue;
        }

        ctx.strokeStyle = SKELETON_COLORS[edge.part] ?? '#e2e8f0';
        ctx.beginPath();
        ctx.moveTo(from.x, from.y);
        ctx.lineTo(to.x, to.y);
        ctx.stroke();
      }

      // Individual vertices of a 478 point mesh are noise, not information.
      if (!isFace) {
        const radius = isHand ? 2.5 : 4;
        for (const point of points) {
          if (point.score <= 0) {
            continue;
          }
          ctx.beginPath();
          ctx.arc(point.x, point.y, radius, 0, Math.PI * 2);
          ctx.fillStyle = '#0f172a';
          ctx.fill();
          ctx.lineWidth = 2;
          ctx.strokeStyle = '#f8fafc';
          ctx.stroke();
        }
      }

      if (isHand && skeleton.label) {
        const { x, y } = skeleton.bbox;
        ctx.font = '12px Inter, sans-serif';
        ctx.fillStyle = '#f8fafc';
        ctx.fillText(skeleton.label, x, Math.max(12, y - 4));
      }
    }
  }

  private drawDetections(ctx: CanvasRenderingContext2D): void {
    const detections = this.filteredDetections();

    detections.forEach(detection => {
      if (detection.confidence < this.confidenceThreshold()) return;

      const { x, y, width, height } = detection.bbox;
      const color = detection.color || '#22c55e';

      ctx.strokeStyle = color;
      ctx.lineWidth = 2;

      // A silhouette says more than the rectangle around it, so it replaces the
      // box rather than being drawn on top of it. Detections the segmenter
      // could not trace still get their box, so nothing disappears.
      if (detection.polygon && detection.polygon.length >= 3) {
        ctx.beginPath();
        ctx.moveTo(detection.polygon[0][0], detection.polygon[0][1]);
        for (let i = 1; i < detection.polygon.length; i++) {
          ctx.lineTo(detection.polygon[i][0], detection.polygon[i][1]);
        }
        ctx.closePath();
        ctx.stroke();
        // A light wash makes the shape read as a surface without hiding what is
        // underneath it.
        ctx.fillStyle = color + '26';
        ctx.fill();
      } else {
        ctx.strokeRect(x, y, width, height);
      }

      // Draw label background
      const label = `${detection.label} ${(detection.confidence * 100).toFixed(0)}%`;
      ctx.font = '14px Inter, sans-serif';
      const textMetrics = ctx.measureText(label);
      const textHeight = 20;

      ctx.fillStyle = detection.color || '#22c55e';
      ctx.fillRect(x, y - textHeight, textMetrics.width + 8, textHeight);

      // Draw label text
      ctx.fillStyle = '#ffffff';
      ctx.fillText(label, x + 4, y - 6);
    });
  }

  private drawBarcodes(ctx: CanvasRenderingContext2D): void {
    const barcodes = this.barcodes();
    const barcodeColor = '#f59e0b'; // Amber color for barcodes

    barcodes.forEach(barcode => {
      const { x, y, width, height } = barcode.bbox;

      // Draw bounding box with dashed line
      ctx.strokeStyle = barcodeColor;
      ctx.lineWidth = 2;
      ctx.setLineDash([5, 5]);
      ctx.strokeRect(x, y, width, height);
      ctx.setLineDash([]);

      // Draw label background
      const label = `${barcode.type}: ${barcode.data}`;
      ctx.font = 'bold 14px Inter, sans-serif';
      const textMetrics = ctx.measureText(label);
      const textHeight = 22;

      // Position label below the barcode
      const labelY = y + height + textHeight;

      ctx.fillStyle = barcodeColor;
      ctx.fillRect(x, y + height, textMetrics.width + 12, textHeight);

      // Draw label text
      ctx.fillStyle = '#000000';
      ctx.fillText(label, x + 6, labelY - 6);
    });
  }

  openCaptureModal(detection: Detection): void {
    // Capture current frame before opening modal
    const video = this.videoElement?.nativeElement;
    if (video) {
      this.lastFrameBase64.set(this.detectionService.captureFrame(video, 0.9));
    }

    this.selectedDetection.set(detection);
    this.captureObjectName.set('');
    this.captureObjectDescription.set('');
    this.showCaptureModal.set(true);
  }

  closeCaptureModal(): void {
    this.showCaptureModal.set(false);
    this.selectedDetection.set(null);
    this.captureObjectName.set('');
    this.captureObjectDescription.set('');
  }

  saveDetectionAsObject(): void {
    const detection = this.selectedDetection();
    const name = this.captureObjectName().trim();

    if (!detection || !name) return;

    const video = this.videoElement?.nativeElement;
    if (!video) {
      this.errorMessage.set('view.errors.saveFailed');
      return;
    }

    this.isSaving.set(true);

    // Crop the detection region on frontend
    const croppedImage = this.cropDetectionRegion(video, detection.bbox);

    // The backend handles both new and existing objects:
    // - If object with this name exists, adds image to it
    // - If not, creates new object
    // - In both cases, automatically refreshes features for immediate recognition
    const request: CaptureDetectionRequest = {
      image: croppedImage,
      bbox: { x: 0, y: 0, width: detection.bbox.width, height: detection.bbox.height },
      name,
      description: this.captureObjectDescription().trim() || undefined,
    };

    const existingObject = this.matchingObject();

    this.detectionService.captureDetection(request).subscribe({
      next: response => {
        if (existingObject) {
          console.log(`Image added to existing object "${name}" (${response.trainingSamples} images total)`);
        } else {
          console.log(`New object "${name}" created and trained`);
        }

        // Reload catalog objects for future autocomplete
        this.loadCatalogObjects();

        this.isSaving.set(false);
        this.closeCaptureModal();
      },
      error: err => {
        console.error('Failed to save object:', err);
        this.isSaving.set(false);
        this.errorMessage.set('view.errors.saveFailed');
      },
    });
  }

  private cropDetectionRegion(
    video: HTMLVideoElement,
    bbox: { x: number; y: number; width: number; height: number }
  ): string {
    const canvas = document.createElement('canvas');
    const padding = 10;

    const x = Math.max(0, bbox.x - padding);
    const y = Math.max(0, bbox.y - padding);
    const width = Math.min(video.videoWidth - x, bbox.width + padding * 2);
    const height = Math.min(video.videoHeight - y, bbox.height + padding * 2);

    canvas.width = width;
    canvas.height = height;

    const ctx = canvas.getContext('2d');
    if (!ctx) {
      throw new Error('Failed to get canvas context');
    }

    ctx.drawImage(video, x, y, width, height, 0, 0, width, height);
    return canvas.toDataURL('image/jpeg', 0.9);
  }
}

interface Detection {
  id: string;
  label: string;
  /** How sure the detector is that something is there. */
  confidence: number;
  bbox: {
    x: number;
    y: number;
    width: number;
    height: number;
  };
  color?: string;
  objectId?: string;
  objectName?: string;
  /** How sure the matcher is that it is this particular catalog entry. */
  matchConfidence?: number;
  /** Outline of the object, when segmentation produced one. */
  polygon?: number[][];
}

/**
 * One aggregated entry in the detections list.
 *
 * Holds the best sighting of a thing over the last few seconds rather than the
 * newest one, together with the thumbnail cut from the frame where it looked
 * clearest.
 */
/** How a detection is classified for the badge. */
type DetectionCardType = 'known' | 'human' | 'unknown' | 'other';

/** The slices of the detection list offered as tabs. */
type DetectionTab = 'all' | 'threshold' | 'humans' | 'objects';

interface DetectionCard {
  key: string;
  label: string;
  objectId?: string;
  objectName?: string;
  confidence: number;
  matchConfidence?: number;
  color?: string;
  bbox: { x: number; y: number; width: number; height: number };
  thumbnail: string | null;
  lastSeen: number;
  sightings: number;
}

interface Barcode {
  id: string;
  type: string;
  data: string;
  bbox: {
    x: number;
    y: number;
    width: number;
    height: number;
  };
  quality: number;
}
