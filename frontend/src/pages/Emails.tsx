import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Mail,
  RefreshCw,
  Paperclip,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import {
  getEmails,
  PARSE_STATUS_STYLES,
  type ParseStatus,
  type ProcessedEmail,
} from '../lib/api';
import DocumentViewer from '../components/DocumentViewer';
import InvoiceNumberLink from '../components/InvoiceNumberLink';

const PAGE_SIZE = 50;

const FILTER_TABS: { key: string; label: string }[] = [
  { key: '', label: 'All' },
  { key: 'parsed', label: 'Parsed' },
  { key: 'unparsed', label: 'Unparsed' },
  { key: 'no_attachment', label: 'No attachment' },
  { key: 'failed', label: 'Failed' },
];

const fmtDate = (d: string | null | undefined) => {
  if (!d) return '—';
  try {
    return new Date(d).toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    });
  } catch {
    return d;
  }
};

function ParseStatusBadge({ status }: { status: string | null | undefined }) {
  if (!status) {
    return (
      <span className="text-xs" style={{ color: 'var(--th-text-quaternary)' }}>—</span>
    );
  }
  const ss = PARSE_STATUS_STYLES[status] || {
    bg: 'rgba(148,163,184,0.12)',
    text: '#94a3b8',
    border: 'rgba(148,163,184,0.25)',
    label: status,
  };
  return (
    <span
      className="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium"
      style={{
        backgroundColor: ss.bg,
        color: ss.text,
        border: `1px solid ${ss.border}`,
      }}
      title="Whether the invoice document was successfully parsed (OCR/field extraction)"
    >
      {ss.label}
    </span>
  );
}

export default function Emails() {
  const [parseStatus, setParseStatus] = useState('');
  const [offset, setOffset] = useState(0);
  const [viewer, setViewer] = useState<{ id: string; pdf_path?: string | null } | null>(null);

  const queryParams = useMemo(
    () => ({
      parse_status: parseStatus || undefined,
      limit: PAGE_SIZE,
      offset,
    }),
    [parseStatus, offset],
  );

  const { data, isLoading, isFetching, refetch } = useQuery({
    queryKey: ['emails', queryParams],
    queryFn: () => getEmails(queryParams),
  });

  const emails: ProcessedEmail[] = data?.emails || [];
  const total = data?.total ?? 0;
  const pageStart = total === 0 ? 0 : offset + 1;
  const pageEnd = Math.min(offset + PAGE_SIZE, total);
  const canPrev = offset > 0;
  const canNext = offset + PAGE_SIZE < total;

  const onFilter = (key: string) => {
    setParseStatus(key);
    setOffset(0);
  };

  return (
    <div className="min-h-full p-3 sm:p-6" style={{ backgroundColor: 'var(--th-surface-2)', color: 'var(--th-text-primary)' }}>
      {/* Header */}
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-bold sm:text-xl" style={{ color: 'var(--th-accent)' }}>
            Emails
          </h1>
          <p className="text-sm" style={{ color: 'var(--th-text-tertiary)' }}>
            Received invoice emails and parse status
            {total > 0 ? ` — ${total} total` : ''}
          </p>
        </div>
        <button
          onClick={() => refetch()}
          className="inline-flex items-center rounded px-3 py-2 text-sm font-medium"
          style={{
            backgroundColor: 'var(--th-surface-0)',
            color: 'var(--th-text-secondary)',
            border: '1px solid var(--th-border-strong)',
          }}
          title="Refresh"
        >
          <RefreshCw className={`h-4 w-4 ${isFetching ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Parse-status filter tabs */}
      <div
        className="mb-3 flex flex-wrap gap-1 rounded p-1"
        style={{ backgroundColor: 'var(--th-surface-3)', border: '1px solid var(--th-border-strong)' }}
      >
        {FILTER_TABS.map((tab) => {
          const active = parseStatus === tab.key;
          return (
            <button
              key={tab.key || 'all'}
              onClick={() => onFilter(tab.key)}
              className="rounded px-3 py-1.5 text-xs font-medium transition-colors"
              style={{
                backgroundColor: active ? 'var(--th-active)' : 'transparent',
                color: active ? 'var(--th-text-primary)' : 'var(--th-text-tertiary)',
              }}
            >
              {tab.label}
            </button>
          );
        })}
      </div>

      {/* Table */}
      <div
        className="overflow-hidden rounded"
        style={{ backgroundColor: 'var(--th-surface-3)', border: '1px solid var(--th-border-strong)' }}
      >
        {isLoading ? (
          <div className="flex justify-center py-16">
            <div className="h-8 w-8 animate-spin rounded-full border-4 border-brand border-t-transparent" />
          </div>
        ) : emails.length === 0 ? (
          <div className="py-16 text-center">
            <Mail className="mx-auto h-10 w-10" style={{ color: 'var(--th-text-quaternary)' }} />
            <p className="mt-3 text-sm" style={{ color: 'var(--th-text-tertiary)' }}>
              No emails recorded yet
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full" style={{ borderCollapse: 'separate', borderSpacing: 0 }}>
              <thead style={{ backgroundColor: 'var(--th-surface-2)' }}>
                <tr>
                  <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider" style={{ color: 'var(--th-text-tertiary)' }}>
                    Received
                  </th>
                  <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider hidden md:table-cell" style={{ color: 'var(--th-text-tertiary)' }}>
                    From
                  </th>
                  <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider" style={{ color: 'var(--th-text-tertiary)' }}>
                    Subject
                  </th>
                  <th className="px-4 py-2.5 text-center text-xs font-semibold uppercase tracking-wider hidden sm:table-cell" style={{ color: 'var(--th-text-tertiary)' }}>
                    Att.
                  </th>
                  <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider" style={{ color: 'var(--th-text-tertiary)' }}>
                    Parse Status
                  </th>
                  <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider" style={{ color: 'var(--th-text-tertiary)' }}>
                    Invoice
                  </th>
                </tr>
              </thead>
              <tbody>
                {emails.map((row) => (
                  <tr
                    key={row.message_id}
                    className="transition-colors hover:bg-[var(--th-hover)]"
                    style={{ borderBottom: '1px solid var(--th-border)' }}
                  >
                    <td className="whitespace-nowrap px-4 py-2.5 text-xs" style={{ color: 'var(--th-text-secondary)' }}>
                      {fmtDate(row.received_date || row.processed_at)}
                    </td>
                    <td className="hidden md:table-cell px-4 py-2.5 text-xs max-w-[200px] truncate" style={{ color: 'var(--th-text-secondary)' }} title={row.from_header || undefined}>
                      {row.from_header || '—'}
                    </td>
                    <td className="px-4 py-2.5 text-sm max-w-[280px]">
                      <div className="truncate" style={{ color: 'var(--th-text-primary)' }} title={row.subject || undefined}>
                        {row.subject || '—'}
                      </div>
                      {row.vendor_name && (
                        <div className="text-xs truncate mt-0.5" style={{ color: 'var(--th-text-quaternary)' }}>
                          {row.vendor_name}
                          {row.filename ? ` · ${row.filename}` : ''}
                        </div>
                      )}
                    </td>
                    <td className="hidden sm:table-cell px-4 py-2.5 text-center text-xs" style={{ color: 'var(--th-text-secondary)' }}>
                      {row.attachment_count == null ? (
                        '—'
                      ) : (
                        <span className="inline-flex items-center gap-1">
                          <Paperclip className="h-3 w-3" style={{ color: 'var(--th-text-quaternary)' }} />
                          {row.attachment_count}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-2.5">
                      <ParseStatusBadge status={row.parse_status as ParseStatus | null} />
                    </td>
                    <td className="px-4 py-2.5">
                      {row.invoice_id ? (
                        <InvoiceNumberLink
                          invoiceId={row.invoice_id}
                          pdfPath={row.invoice_pdf_path}
                          onOpen={(id, path) => setViewer({ id, pdf_path: path })}
                        />
                      ) : (
                        <span className="text-xs" style={{ color: 'var(--th-text-quaternary)' }}>—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Pagination */}
      {total > 0 && (
        <div className="mt-3 flex items-center justify-between text-xs" style={{ color: 'var(--th-text-tertiary)' }}>
          <span>
            Showing {pageStart}–{pageEnd} of {total}
          </span>
          <div className="flex items-center gap-2">
            <button
              disabled={!canPrev}
              onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
              className="inline-flex items-center rounded px-2 py-1 disabled:opacity-40"
              style={{ border: '1px solid var(--th-border-strong)', color: 'var(--th-text-secondary)' }}
            >
              <ChevronLeft className="h-3.5 w-3.5" /> Prev
            </button>
            <button
              disabled={!canNext}
              onClick={() => setOffset((o) => o + PAGE_SIZE)}
              className="inline-flex items-center rounded px-2 py-1 disabled:opacity-40"
              style={{ border: '1px solid var(--th-border-strong)', color: 'var(--th-text-secondary)' }}
            >
              Next <ChevronRight className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      )}

      {viewer && (
        <DocumentViewer
          invoiceId={viewer.id}
          pdfPath={viewer.pdf_path}
          onClose={() => setViewer(null)}
        />
      )}
    </div>
  );
}
