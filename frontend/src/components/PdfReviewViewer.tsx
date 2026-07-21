import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import * as pdfjsLib from 'pdfjs-dist';
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
import {
  Loader2,
  ZoomIn,
  ZoomOut,
  MousePointer2,
  Square,
  ChevronLeft,
  ChevronRight,
  AlertTriangle,
  Crop,
} from 'lucide-react';
import { getInvoiceDocumentUrl } from '../lib/api';

pdfjsLib.GlobalWorkerOptions.workerSrc = workerUrl;

const MIN_SCALE = 1.0;
const MAX_SCALE = 3.0;
const SCALE_STEP = 0.25;
const DEFAULT_SCALE = 1.5;
const INITIAL_PAGES = 5;

export type SelectionMode = 'text' | 'area';

interface PdfReviewViewerProps {
  invoiceId: string;
  pdfPath: string | null;
  onTextSelected?: (text: string) => void;
  onAreaSelected?: (base64Png: string) => void;
  extracting?: boolean;
}

interface TextItemPos {
  str: string;
  left: number;
  top: number;
  fontSize: number;
  width: number;
  height: number;
  transform: string;
}

interface PageRender {
  pageNum: number;
  width: number;
  height: number;
  canvas: HTMLCanvasElement | null;
  textItems: TextItemPos[];
}

interface AreaRect {
  pageNum: number;
  x: number;
  y: number;
  w: number;
  h: number;
}

function isHtmlPath(pdfPath: string | null): boolean {
  if (!pdfPath) return false;
  const lower = pdfPath.toLowerCase();
  return lower.endsWith('.html') || lower.endsWith('.htm');
}

function stripDataUrl(dataUrl: string): string {
  if (dataUrl.startsWith('data:') && dataUrl.includes(',')) {
    return dataUrl.split(',', 2)[1] || '';
  }
  return dataUrl;
}

export default function PdfReviewViewer({
  invoiceId,
  pdfPath,
  onTextSelected,
  onAreaSelected,
  extracting = false,
}: PdfReviewViewerProps) {
  const [mode, setMode] = useState<SelectionMode>('text');
  const [scale, setScale] = useState(DEFAULT_SCALE);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [numPages, setNumPages] = useState(0);
  const [pagesLoaded, setPagesLoaded] = useState(0);
  const [pageRenders, setPageRenders] = useState<PageRender[]>([]);
  const [selectedText, setSelectedText] = useState('');
  const [textBtnPos, setTextBtnPos] = useState<{ x: number; y: number } | null>(null);
  const [areaRect, setAreaRect] = useState<AreaRect | null>(null);
  const [dragging, setDragging] = useState(false);
  const dragStart = useRef<{ pageNum: number; x: number; y: number } | null>(null);

  const containerRef = useRef<HTMLDivElement>(null);
  const pageCanvasRefs = useRef<Map<number, HTMLCanvasElement>>(new Map());
  const pdfDocRef = useRef<pdfjsLib.PDFDocumentProxy | null>(null);
  const htmlIframeRef = useRef<HTMLIFrameElement>(null);
  const loadGen = useRef(0);

  const docUrl = useMemo(() => getInvoiceDocumentUrl(invoiceId, false), [invoiceId]);
  const html = isHtmlPath(pdfPath);

  const resetSelection = useCallback(() => {
    setSelectedText('');
    setTextBtnPos(null);
    setAreaRect(null);
    setDragging(false);
    dragStart.current = null;
    const sel = window.getSelection();
    if (sel) sel.removeAllRanges();
  }, []);

  // Cleanup PDF when unmounting / switching invoice
  useEffect(() => {
    return () => {
      const doc = pdfDocRef.current as { destroy?: () => Promise<void> } | null;
      doc?.destroy?.().catch(() => {});
      pdfDocRef.current = null;
    };
  }, []);

  // Load PDF document
  useEffect(() => {
    if (html || !pdfPath) {
      setPageRenders([]);
      setNumPages(0);
      setPagesLoaded(0);
      setLoading(false);
      setError(null);
      return;
    }

    const gen = ++loadGen.current;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setPageRenders([]);
    setNumPages(0);
    setPagesLoaded(0);
    resetSelection();

    (async () => {
      try {
        const prev = pdfDocRef.current as { destroy?: () => Promise<void> } | null;
        prev?.destroy?.().catch(() => {});
        pdfDocRef.current = null;

        const loadingTask = pdfjsLib.getDocument({
          url: docUrl,
          withCredentials: false,
        });
        const pdf = await loadingTask.promise;
        if (cancelled || gen !== loadGen.current) {
          (pdf as { destroy?: () => Promise<void> }).destroy?.().catch(() => {});
          return;
        }
        pdfDocRef.current = pdf;
        setNumPages(pdf.numPages);
        setPagesLoaded(Math.min(INITIAL_PAGES, pdf.numPages));
      } catch (e) {
        if (!cancelled && gen === loadGen.current) {
          const msg = e instanceof Error ? e.message : 'Failed to load PDF';
          setError(msg);
          setLoading(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [docUrl, pdfPath, html, resetSelection]);

  // Render pages when scale or pagesLoaded changes
  useEffect(() => {
    const pdf = pdfDocRef.current;
    if (!pdf || pagesLoaded <= 0 || html) return;

    const gen = loadGen.current;
    let cancelled = false;
    setLoading(true);

    (async () => {
      try {
        const renders: PageRender[] = [];
        for (let pageNum = 1; pageNum <= pagesLoaded; pageNum++) {
          if (cancelled || gen !== loadGen.current) return;
          const page = await pdf.getPage(pageNum);
          const viewport = page.getViewport({ scale });
          const canvas = document.createElement('canvas');
          const ctx = canvas.getContext('2d');
          if (!ctx) continue;
          canvas.width = Math.floor(viewport.width);
          canvas.height = Math.floor(viewport.height);

          await page.render({
            canvasContext: ctx,
            viewport,
            canvas,
          }).promise;

          const textContent = await page.getTextContent();
          const textItems: TextItemPos[] = [];
          for (const item of textContent.items) {
            if (!('str' in item) || !item.str) continue;
            const tx = pdfjsLib.Util.transform(viewport.transform, item.transform);
            const fontHeight = Math.sqrt(tx[2] * tx[2] + tx[3] * tx[3]);
            const width = (item.width || 0) * scale;
            // PDF y is from bottom; canvas y is from top
            const left = tx[4];
            const top = tx[5] - fontHeight;
            const angle = Math.atan2(tx[1], tx[0]);
            textItems.push({
              str: item.str,
              left,
              top,
              fontSize: fontHeight,
              width: width || fontHeight * item.str.length * 0.5,
              height: fontHeight,
              transform: angle ? `rotate(${angle}rad)` : '',
            });
          }

          renders.push({
            pageNum,
            width: viewport.width,
            height: viewport.height,
            canvas,
            textItems,
          });
        }
        if (!cancelled && gen === loadGen.current) {
          setPageRenders(renders);
          setLoading(false);
        }
      } catch (e) {
        if (!cancelled && gen === loadGen.current) {
          setError(e instanceof Error ? e.message : 'Failed to render PDF');
          setLoading(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [pagesLoaded, scale, html, numPages]);

  // Paint rendered canvases into DOM canvases when pageRenders updates
  useEffect(() => {
    for (const pr of pageRenders) {
      const dest = pageCanvasRefs.current.get(pr.pageNum);
      if (!dest || !pr.canvas) continue;
      dest.width = pr.canvas.width;
      dest.height = pr.canvas.height;
      const ctx = dest.getContext('2d');
      if (ctx) {
        ctx.clearRect(0, 0, dest.width, dest.height);
        ctx.drawImage(pr.canvas, 0, 0);
      }
    }
  }, [pageRenders]);

  // Text selection listener
  useEffect(() => {
    if (mode !== 'text') return;

    const onSelChange = () => {
      const sel = window.getSelection();
      if (!sel || sel.isCollapsed || !sel.rangeCount) {
        setSelectedText('');
        setTextBtnPos(null);
        return;
      }
      const text = sel.toString().trim();
      if (!text) {
        setSelectedText('');
        setTextBtnPos(null);
        return;
      }
      // Only react to selections inside our container
      const anchor = sel.anchorNode;
      if (!anchor || !containerRef.current?.contains(anchor)) {
        return;
      }
      setSelectedText(text);
      try {
        const range = sel.getRangeAt(0);
        const rect = range.getBoundingClientRect();
        const crect = containerRef.current.getBoundingClientRect();
        setTextBtnPos({
          x: rect.left + rect.width / 2 - crect.left + containerRef.current.scrollLeft,
          y: rect.top - crect.top + containerRef.current.scrollTop - 8,
        });
      } catch {
        setTextBtnPos(null);
      }
    };

    document.addEventListener('selectionchange', onSelChange);
    return () => document.removeEventListener('selectionchange', onSelChange);
  }, [mode]);

  // HTML iframe text selection: poll selection from contentWindow
  useEffect(() => {
    if (!html || mode !== 'text') return;
    const timer = window.setInterval(() => {
      try {
        const iframe = htmlIframeRef.current;
        const win = iframe?.contentWindow;
        if (!win) return;
        const sel = win.getSelection();
        const text = sel?.toString().trim() || '';
        if (text && text !== selectedText) {
          setSelectedText(text);
          // Place button near top of iframe area
          setTextBtnPos({ x: 80, y: 40 });
        } else if (!text && selectedText) {
          setSelectedText('');
          setTextBtnPos(null);
        }
      } catch {
        // cross-origin or not ready
      }
    }, 400);
    return () => window.clearInterval(timer);
  }, [html, mode, selectedText]);

  const handleZoom = (delta: number) => {
    setScale((s) => Math.min(MAX_SCALE, Math.max(MIN_SCALE, Math.round((s + delta) * 100) / 100)));
    resetSelection();
  };

  const handleModeChange = (m: SelectionMode) => {
    setMode(m);
    resetSelection();
  };

  const onPageMouseDown = (pageNum: number, e: React.MouseEvent<HTMLDivElement>) => {
    if (mode !== 'area') return;
    e.preventDefault();
    const el = e.currentTarget;
    const rect = el.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    dragStart.current = { pageNum, x, y };
    setDragging(true);
    setAreaRect({ pageNum, x, y, w: 0, h: 0 });
  };

  const onPageMouseMove = (pageNum: number, e: React.MouseEvent<HTMLDivElement>) => {
    if (mode !== 'area' || !dragging || !dragStart.current) return;
    if (dragStart.current.pageNum !== pageNum) return;
    const el = e.currentTarget;
    const rect = el.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    const sx = dragStart.current.x;
    const sy = dragStart.current.y;
    setAreaRect({
      pageNum,
      x: Math.min(sx, x),
      y: Math.min(sy, y),
      w: Math.abs(x - sx),
      h: Math.abs(y - sy),
    });
  };

  const onPageMouseUp = () => {
    if (mode !== 'area') return;
    setDragging(false);
    dragStart.current = null;
    setAreaRect((r) => {
      if (!r || r.w < 4 || r.h < 4) return null;
      return r;
    });
  };

  const handleExtractText = () => {
    if (!selectedText || !onTextSelected) return;
    onTextSelected(selectedText);
  };

  const handleExtractArea = () => {
    if (!areaRect || !onAreaSelected) return;
    const canvas = pageCanvasRefs.current.get(areaRect.pageNum);
    if (!canvas) return;
    const crop = document.createElement('canvas');
    const w = Math.max(1, Math.round(areaRect.w));
    const h = Math.max(1, Math.round(areaRect.h));
    crop.width = w;
    crop.height = h;
    const ctx = crop.getContext('2d');
    if (!ctx) return;
    ctx.drawImage(
      canvas,
      Math.round(areaRect.x),
      Math.round(areaRect.y),
      w,
      h,
      0,
      0,
      w,
      h,
    );
    const dataUrl = crop.toDataURL('image/png');
    const b64 = stripDataUrl(dataUrl);
    onAreaSelected(b64);
  };

  const toolbarBtn = (active: boolean): React.CSSProperties => ({
    backgroundColor: active ? 'var(--th-accent)' : 'var(--th-surface-2)',
    color: active ? '#fff' : 'var(--th-text-secondary)',
    border: `1px solid ${active ? 'var(--th-accent)' : 'var(--th-border)'}`,
  });

  // No stored file
  if (!pdfPath) {
    return (
      <div
        className="flex h-full min-h-[240px] flex-col items-center justify-center gap-2 p-6 text-center rounded-lg"
        style={{ backgroundColor: 'var(--th-surface-2)', border: '1px solid var(--th-border)' }}
      >
        <AlertTriangle className="h-8 w-8" style={{ color: 'var(--th-text-quaternary)' }} />
        <p className="text-sm font-medium" style={{ color: 'var(--th-text-primary)' }}>
          No document on file
        </p>
        <p className="text-xs max-w-xs" style={{ color: 'var(--th-text-tertiary)' }}>
          Use the raw text panel (if available) to select text for extraction.
        </p>
      </div>
    );
  }

  // HTML document via iframe
  if (html) {
    return (
      <div className="flex flex-col h-full min-h-[320px]">
        <div
          className="flex flex-wrap items-center gap-2 px-2 py-1.5 rounded-t-lg"
          style={{ backgroundColor: 'var(--th-surface-1)', border: '1px solid var(--th-border)', borderBottom: 'none' }}
        >
          <span className="text-xs font-medium" style={{ color: 'var(--th-text-tertiary)' }}>
            HTML document — select text inside the preview
          </span>
          {selectedText && onTextSelected && (
            <button
              type="button"
              disabled={extracting}
              onClick={handleExtractText}
              className="inline-flex items-center gap-1 ml-auto px-2.5 py-1 text-xs font-semibold text-white rounded disabled:opacity-50"
              style={{ backgroundColor: 'var(--color-brand)' }}
            >
              {extracting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Crop className="h-3.5 w-3.5" />}
              Extract Selection
            </button>
          )}
        </div>
        <div
          className="relative flex-1 min-h-[280px] rounded-b-lg overflow-hidden"
          style={{ border: '1px solid var(--th-border)', backgroundColor: 'var(--th-surface-2)' }}
        >
          <iframe
            ref={htmlIframeRef}
            title={`Invoice ${invoiceId} HTML`}
            src={docUrl}
            className="w-full h-full border-0 min-h-[280px]"
            sandbox="allow-same-origin"
          />
        </div>
        {selectedText && (
          <p className="mt-1 text-[11px] truncate" style={{ color: 'var(--th-text-quaternary)' }}>
            Selected: {selectedText.slice(0, 120)}
            {selectedText.length > 120 ? '…' : ''}
          </p>
        )}
      </div>
    );
  }

  // PDF via PDF.js
  return (
    <div className="flex flex-col h-full min-h-[320px]">
      {/* Toolbar */}
      <div
        className="flex flex-wrap items-center gap-1.5 px-2 py-1.5 rounded-t-lg"
        style={{
          backgroundColor: 'var(--th-surface-1)',
          border: '1px solid var(--th-border)',
          borderBottom: 'none',
        }}
      >
        <button
          type="button"
          onClick={() => handleModeChange('text')}
          className="inline-flex items-center gap-1 px-2 py-1 text-xs font-medium rounded"
          style={toolbarBtn(mode === 'text')}
          title="Select text on the PDF"
        >
          <MousePointer2 className="h-3.5 w-3.5" />
          Select Text
        </button>
        <button
          type="button"
          onClick={() => handleModeChange('area')}
          className="inline-flex items-center gap-1 px-2 py-1 text-xs font-medium rounded"
          style={toolbarBtn(mode === 'area')}
          title="Draw a rectangle to crop"
        >
          <Square className="h-3.5 w-3.5" />
          Select Area
        </button>

        <span className="mx-1 h-4 w-px" style={{ backgroundColor: 'var(--th-border)' }} />

        <button
          type="button"
          onClick={() => handleZoom(-SCALE_STEP)}
          disabled={scale <= MIN_SCALE}
          className="inline-flex items-center p-1 rounded disabled:opacity-40"
          style={toolbarBtn(false)}
          aria-label="Zoom out"
        >
          <ZoomOut className="h-3.5 w-3.5" />
        </button>
        <span className="text-[11px] tabular-nums px-1" style={{ color: 'var(--th-text-tertiary)' }}>
          {Math.round(scale * 100)}%
        </span>
        <button
          type="button"
          onClick={() => handleZoom(SCALE_STEP)}
          disabled={scale >= MAX_SCALE}
          className="inline-flex items-center p-1 rounded disabled:opacity-40"
          style={toolbarBtn(false)}
          aria-label="Zoom in"
        >
          <ZoomIn className="h-3.5 w-3.5" />
        </button>

        {numPages > 0 && (
          <>
            <span className="mx-1 h-4 w-px" style={{ backgroundColor: 'var(--th-border)' }} />
            <span className="text-[11px]" style={{ color: 'var(--th-text-tertiary)' }}>
              {pagesLoaded}/{numPages} pages
            </span>
            {pagesLoaded < numPages && (
              <button
                type="button"
                onClick={() => setPagesLoaded((n) => Math.min(numPages, n + INITIAL_PAGES))}
                className="inline-flex items-center gap-0.5 px-2 py-1 text-xs rounded"
                style={toolbarBtn(false)}
              >
                <ChevronRight className="h-3 w-3" />
                Load more
              </button>
            )}
            {pagesLoaded > INITIAL_PAGES && (
              <button
                type="button"
                onClick={() => {
                  setPagesLoaded(INITIAL_PAGES);
                  resetSelection();
                }}
                className="inline-flex items-center gap-0.5 px-2 py-1 text-xs rounded"
                style={toolbarBtn(false)}
              >
                <ChevronLeft className="h-3 w-3" />
                Reset
              </button>
            )}
          </>
        )}

        {mode === 'area' && areaRect && areaRect.w >= 4 && areaRect.h >= 4 && onAreaSelected && (
          <button
            type="button"
            disabled={extracting}
            onClick={handleExtractArea}
            className="inline-flex items-center gap-1 ml-auto px-2.5 py-1 text-xs font-semibold text-white rounded disabled:opacity-50"
            style={{ backgroundColor: 'var(--color-brand)' }}
          >
            {extracting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Crop className="h-3.5 w-3.5" />}
            Extract Area
          </button>
        )}
      </div>

      {/* Scrollable pages */}
      <div
        ref={containerRef}
        className="relative flex-1 overflow-auto rounded-b-lg min-h-[280px]"
        style={{
          border: '1px solid var(--th-border)',
          backgroundColor: 'var(--th-surface-2)',
        }}
      >
        {loading && pageRenders.length === 0 && (
          <div className="flex items-center justify-center gap-2 py-16 text-sm" style={{ color: 'var(--th-text-tertiary)' }}>
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading PDF…
          </div>
        )}

        {error && (
          <div className="flex items-start gap-2 p-4 text-sm" style={{ color: 'var(--th-danger)' }}>
            <AlertTriangle className="h-4 w-4 flex-shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        )}

        <div className="flex flex-col items-center gap-4 p-3">
          {pageRenders.map((pr) => (
            <div
              key={pr.pageNum}
              className="relative shadow-md"
              style={{
                width: pr.width,
                height: pr.height,
                cursor: mode === 'area' ? 'crosshair' : 'text',
                userSelect: mode === 'text' ? 'text' : 'none',
              }}
              onMouseDown={(e) => onPageMouseDown(pr.pageNum, e)}
              onMouseMove={(e) => onPageMouseMove(pr.pageNum, e)}
              onMouseUp={onPageMouseUp}
              onMouseLeave={() => {
                if (dragging) onPageMouseUp();
              }}
            >
              <canvas
                ref={(el) => {
                  if (el) pageCanvasRefs.current.set(pr.pageNum, el);
                  else pageCanvasRefs.current.delete(pr.pageNum);
                }}
                className="block absolute inset-0"
                style={{ width: pr.width, height: pr.height }}
              />

              {/* Text layer */}
              {mode === 'text' && (
                <div
                  className="absolute inset-0 overflow-hidden"
                  style={{
                    width: pr.width,
                    height: pr.height,
                    lineHeight: 1,
                    // Transparent text over canvas for native selection
                    opacity: 1,
                  }}
                >
                  {pr.textItems.map((ti, i) => (
                    <span
                      key={`${pr.pageNum}-${i}`}
                      style={{
                        position: 'absolute',
                        left: ti.left,
                        top: ti.top,
                        fontSize: `${ti.fontSize}px`,
                        fontFamily: 'sans-serif',
                        whiteSpace: 'pre',
                        transformOrigin: '0% 0%',
                        transform: ti.transform || undefined,
                        color: 'transparent',
                        // Improve hit testing / selection
                        letterSpacing: 0,
                        pointerEvents: 'all',
                      }}
                    >
                      {ti.str}
                    </span>
                  ))}
                </div>
              )}

              {/* Area selection overlay */}
              {mode === 'area' && areaRect && areaRect.pageNum === pr.pageNum && (
                <div
                  className="absolute pointer-events-none"
                  style={{
                    left: areaRect.x,
                    top: areaRect.y,
                    width: areaRect.w,
                    height: areaRect.h,
                    border: '2px solid var(--th-accent)',
                    backgroundColor: 'rgba(57, 216, 189, 0.15)',
                  }}
                />
              )}

              <div
                className="absolute top-1 left-1 text-[10px] px-1.5 py-0.5 rounded pointer-events-none"
                style={{
                  backgroundColor: 'rgba(0,0,0,0.45)',
                  color: '#fff',
                }}
              >
                p.{pr.pageNum}
              </div>
            </div>
          ))}
        </div>

        {/* Floating extract for text selection */}
        {mode === 'text' && selectedText && textBtnPos && onTextSelected && (
          <button
            type="button"
            disabled={extracting}
            onClick={handleExtractText}
            className="absolute z-10 inline-flex items-center gap-1 px-2.5 py-1.5 text-xs font-semibold text-white rounded shadow-lg disabled:opacity-50"
            style={{
              backgroundColor: 'var(--color-brand)',
              left: Math.max(8, textBtnPos.x - 60),
              top: Math.max(8, textBtnPos.y - 28),
            }}
          >
            {extracting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Crop className="h-3.5 w-3.5" />}
            Extract Selection
          </button>
        )}
      </div>

      {mode === 'text' && selectedText && (
        <p className="mt-1 text-[11px] truncate" style={{ color: 'var(--th-text-quaternary)' }}>
          Selected: {selectedText.slice(0, 140)}
          {selectedText.length > 140 ? '…' : ''}
        </p>
      )}
    </div>
  );
}
