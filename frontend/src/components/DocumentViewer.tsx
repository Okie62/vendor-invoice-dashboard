import { useEffect, useMemo } from 'react';
import { X, FileText, Download, ExternalLink } from 'lucide-react';
import { getInvoiceDocumentUrl } from '../lib/api';

interface DocumentViewerProps {
  invoiceId: string | null;
  pdfPath?: string | null;
  onClose: () => void;
  title?: string;
}

/**
 * Modal that shows the stored invoice document (PDF or HTML) in an iframe.
 * Auth is via ?token= on the document URL (localStorage JWT) so the iframe
 * can load without setting Authorization headers.
 */
export default function DocumentViewer({
  invoiceId,
  pdfPath,
  onClose,
  title,
}: DocumentViewerProps) {
  const hasFile = Boolean(invoiceId && pdfPath);

  const docUrl = useMemo(() => {
    if (!invoiceId) return null;
    return getInvoiceDocumentUrl(invoiceId, false);
  }, [invoiceId]);

  const downloadUrl = useMemo(() => {
    if (!invoiceId) return null;
    return getInvoiceDocumentUrl(invoiceId, true);
  }, [invoiceId]);

  const isHtml = useMemo(() => {
    if (!pdfPath) return false;
    const lower = pdfPath.toLowerCase();
    return lower.endsWith('.html') || lower.endsWith('.htm');
  }, [pdfPath]);

  // Close on Escape
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  if (!invoiceId) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6"
      style={{ backgroundColor: 'rgba(0,0,0,0.55)' }}
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Invoice document viewer"
    >
      <div
        className="flex flex-col w-full max-w-5xl h-[90vh] rounded-lg overflow-hidden shadow-2xl"
        style={{ backgroundColor: 'var(--th-surface-0)', border: '1px solid var(--th-border-strong)' }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between gap-3 px-4 py-3"
          style={{ borderBottom: '1px solid var(--th-border)', backgroundColor: 'var(--th-surface-1)' }}
        >
          <div className="min-w-0 flex items-center gap-2">
            <FileText className="h-4 w-4 flex-shrink-0" style={{ color: 'var(--th-accent)' }} />
            <div className="min-w-0">
              <p className="text-sm font-semibold truncate" style={{ color: 'var(--th-text-primary)' }}>
                {title || `Invoice ${invoiceId}`}
              </p>
              <p className="text-xs truncate" style={{ color: 'var(--th-text-tertiary)' }}>
                {hasFile ? (isHtml ? 'HTML document' : 'PDF document') : 'No document on file'}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            {hasFile && downloadUrl && (
              <a
                href={downloadUrl}
                download
                className="inline-flex items-center gap-1 rounded px-2.5 py-1.5 text-xs font-medium"
                style={{
                  border: '1px solid var(--th-border-strong)',
                  color: 'var(--th-text-secondary)',
                }}
              >
                <Download className="h-3.5 w-3.5" />
                Download
              </a>
            )}
            {hasFile && docUrl && (
              <a
                href={docUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 rounded px-2.5 py-1.5 text-xs font-medium"
                style={{
                  border: '1px solid var(--th-border-strong)',
                  color: 'var(--th-text-secondary)',
                }}
              >
                <ExternalLink className="h-3.5 w-3.5" />
                Open
              </a>
            )}
            <button
              onClick={onClose}
              className="rounded p-1.5"
              style={{ color: 'var(--th-text-tertiary)' }}
              aria-label="Close document viewer"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 min-h-0" style={{ backgroundColor: 'var(--th-surface-2)' }}>
          {!hasFile || !docUrl ? (
            <div className="flex h-full flex-col items-center justify-center gap-2 p-8 text-center">
              <FileText className="h-10 w-10" style={{ color: 'var(--th-text-quaternary)' }} />
              <p className="text-sm font-medium" style={{ color: 'var(--th-text-primary)' }}>
                No document available
              </p>
              <p className="text-xs max-w-sm" style={{ color: 'var(--th-text-tertiary)' }}>
                This invoice has no stored PDF or HTML file (legacy or unparsed record without an attachment).
              </p>
            </div>
          ) : isHtml ? (
            <iframe
              title={`Invoice ${invoiceId} HTML`}
              src={docUrl}
              className="w-full h-full border-0"
              sandbox="allow-same-origin"
              // intentionally no scripts for saved HTML receipts
            />
          ) : (
            <iframe
              title={`Invoice ${invoiceId} PDF`}
              src={docUrl}
              className="w-full h-full border-0"
            />
          )}
        </div>
      </div>
    </div>
  );
}
