import type { MouseEvent } from 'react';

interface InvoiceNumberLinkProps {
  invoiceId: string;
  pdfPath?: string | null;
  onOpen: (invoiceId: string, pdfPath?: string | null) => void;
  className?: string;
  prefix?: string;
}

/**
 * Clickable invoice id — accent color + hover underline.
 * Stops row-level click propagation so list navigation doesn't fire.
 */
export default function InvoiceNumberLink({
  invoiceId,
  pdfPath,
  onOpen,
  className = '',
  prefix = '#',
}: InvoiceNumberLinkProps) {
  const handleClick = (e: MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    onOpen(invoiceId, pdfPath);
  };

  return (
    <button
      type="button"
      onClick={handleClick}
      className={`font-mono text-xs hover:underline ${className}`}
      style={{ color: 'var(--th-accent)' }}
      title={pdfPath ? 'View document' : 'Open document viewer'}
    >
      {prefix}{invoiceId}
    </button>
  );
}
