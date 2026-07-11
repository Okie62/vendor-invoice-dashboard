import { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Building2,
  ArrowLeft,
  FileText,
  DollarSign,
  AlertTriangle,
  Clock,
  ChevronDown,
  ChevronUp,
  Check,
  ExternalLink,
  X,
  MoreHorizontal,
} from 'lucide-react';
import {
  getVendorDetail,
  getFormats,
  updateInvoiceStatus,
  STATUS_STYLES,
  VALID_STATUSES,
  type InvoiceStatus,
  type DBInvoice,
} from '../lib/api';
import DocumentViewer from '../components/DocumentViewer';
import InvoiceNumberLink from '../components/InvoiceNumberLink';

const currency = (v: number) =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(v);

const fmtDate = (d: string | null | undefined) => {
  if (!d) return '—';
  try { return new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }); }
  catch { return d; }
};

const statusFlow: Record<string, string> = {
  received: 'needs_review',
  needs_review: 'approved',
  approved: 'scheduled',
  scheduled: 'paid',
};
const prevStatus: Record<string, string> = {
  needs_review: 'received',
  approved: 'needs_review',
  scheduled: 'approved',
};
const canAdvance = (s: string): boolean => s in statusFlow && s !== 'paid';
const canRegress = (s: string): boolean => s in prevStatus;

export default function VendorDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const vendorId = parseInt(id || '0', 10);

  const { data: detail, isLoading } = useQuery({
    queryKey: ['vendor-detail', vendorId],
    queryFn: () => getVendorDetail(vendorId),
    enabled: !isNaN(vendorId) && vendorId > 0,
  });

  const { data: formats = [] } = useQuery({
    queryKey: ['formats'],
    queryFn: getFormats,
  });

  const [invoiceSortAsc, setInvoiceSortAsc] = useState(false);
  const [viewerInvoice, setViewerInvoice] = useState<{ id: string; pdf_path?: string | null } | null>(null);

  const statusMut = useMutation({
    mutationFn: ({ id, status }: { id: string; status: InvoiceStatus }) => updateInvoiceStatus(id, status),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['vendor-detail', vendorId] });
      qc.invalidateQueries({ queryKey: ['invoices'] });
      qc.invalidateQueries({ queryKey: ['dashboard'] });
    },
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-brand border-t-transparent" />
      </div>
    );
  }

  if (!detail) {
    return (
      <div className="p-6">
        <button onClick={() => navigate('/vendors')} className="inline-flex items-center gap-1 text-sm mb-4" style={{ color: 'var(--th-accent)' }}>
          <ArrowLeft className="h-4 w-4" /> Back to Vendors
        </button>
        <p style={{ color: 'var(--th-text-tertiary)' }}>Vendor not found</p>
      </div>
    );
  }

  const { vendor, totals, aging, invoices, formats: vendorFormats } = detail;
  const vendorFormatsList = formats.filter(f => f.vendor_id === vendorId);

  // Sort invoices by created_at
  const sortedInvoices = [...(invoices || [])].sort((a, b) => {
    const da = a.created_at || '';
    const db = b.created_at || '';
    return invoiceSortAsc ? da.localeCompare(db) : db.localeCompare(da);
  });

  return (
    <div className="min-h-full p-3 sm:p-6 space-y-4 sm:space-y-6" style={{ backgroundColor: 'var(--th-surface-1)' }}>
      {/* Back button */}
      <button onClick={() => navigate('/vendors')} className="inline-flex items-center gap-1 text-sm font-medium" style={{ color: 'var(--th-accent)' }}>
        <ArrowLeft className="h-4 w-4" /> Back to Vendors
      </button>

      {/* Vendor Header */}
      <div className="rounded-lg p-5" style={{ backgroundColor: 'var(--th-surface-0)', border: '1px solid var(--th-border)' }}>
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg" style={{ backgroundColor: 'rgba(57,216,189,0.12)', color: 'var(--th-accent)' }}>
                <Building2 className="h-5 w-5" />
              </div>
              <div>
                <h1 className="text-lg font-semibold" style={{ color: 'var(--th-text-primary)' }}>{vendor.name}</h1>
                {vendor.email_domain && (
                  <p className="text-xs mt-0.5" style={{ color: 'var(--th-text-tertiary)' }}>{vendor.email_domain}</p>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Summary Cards */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-5">
          <MiniCard icon={<FileText className="h-4 w-4" />} color="var(--th-accent)" label="Invoices" value={String(totals.invoice_count)} />
          <MiniCard icon={<DollarSign className="h-4 w-4" />} color="#f59e0b" label="Total Charges" value={currency(totals.total_new_charges)} />
          <MiniCard icon={<AlertTriangle className="h-4 w-4" />} color="#ef4444" label="Outstanding" value={currency(totals.total_outstanding)} />
          <MiniCard icon={<Check className="h-4 w-4" />} color="#27a644" label="Total Paid" value={currency(totals.total_paid)} />
        </div>
      </div>

      {/* Aging + Formats row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* A/P Aging for this vendor */}
        <div className="rounded-lg p-5" style={{ backgroundColor: 'var(--th-surface-0)', border: '1px solid var(--th-border)' }}>
          <h2 className="text-sm font-semibold mb-3 flex items-center gap-2" style={{ color: 'var(--th-text-primary)' }}>
            <Clock className="h-4 w-4" style={{ color: 'var(--th-accent)' }} />
            A/P Aging
          </h2>
          {(() => {
            const buckets = [
              { label: 'Current', value: aging.current, color: '#27a644' },
              { label: '1–30 days', value: aging.days_1_30, color: '#f59e0b' },
              { label: '31–60 days', value: aging.days_31_60, color: '#f97316' },
              { label: '61–90 days', value: aging.days_61_90, color: '#ef4444' },
              { label: '90+ days', value: aging.days_90_plus, color: '#dc2626' },
              { label: 'No due date', value: aging.no_due_date, color: '#94a3b8' },
            ];
            const total = buckets.reduce((s, b) => s + b.value, 0);
            return total === 0 ? (
              <p className="py-4 text-center text-sm" style={{ color: 'var(--th-text-tertiary)' }}>No outstanding</p>
            ) : (
              <div className="space-y-2">
                <div className="h-3 rounded-full overflow-hidden flex" style={{ backgroundColor: 'var(--th-surface-2)' }}>
                  {buckets.filter(b => b.value > 0).map(b => (
                    <div key={b.label} style={{ width: `${(b.value / total) * 100}%`, backgroundColor: b.color, minWidth: '4px' }} />
                  ))}
                </div>
                <div className="space-y-1">
                  {buckets.map(b => (
                    <div key={b.label} className="flex items-center justify-between text-xs">
                      <div className="flex items-center gap-2">
                        <span className="inline-block w-2 h-2 rounded-full" style={{ backgroundColor: b.color }} />
                        <span style={{ color: 'var(--th-text-tertiary)' }}>{b.label}</span>
                      </div>
                      <span className="font-medium" style={{ color: 'var(--th-text-secondary)' }}>
                        {currency(b.value)}
                      </span>
                    </div>
                  ))}
                </div>
                <div className="pt-2 border-t flex justify-between text-xs font-semibold" style={{ borderColor: 'var(--th-border)', color: 'var(--th-text-primary)' }}>
                  <span>Total Outstanding</span>
                  <span>{currency(total)}</span>
                </div>
              </div>
            );
          })()}
        </div>

        {/* Registered Formats */}
        <div className="rounded-lg p-5" style={{ backgroundColor: 'var(--th-surface-0)', border: '1px solid var(--th-border)' }}>
          <h2 className="text-sm font-semibold mb-3" style={{ color: 'var(--th-text-primary)' }}>Registered Formats</h2>
          {vendorFormatsList.length === 0 ? (
            <p className="py-4 text-center text-sm" style={{ color: 'var(--th-text-tertiary)' }}>No formats registered</p>
          ) : (
            <div className="space-y-2">
              {vendorFormatsList.slice(0, 5).map((f, i) => (
                <div key={f.id || i} className="p-2 rounded text-xs" style={{ backgroundColor: 'var(--th-surface-2)' }}>
                  <div className="flex items-center justify-between mb-1">
                    <span className="font-medium" style={{ color: 'var(--th-text-secondary)' }}>{f.parser_name}</span>
                    <span
                      className="inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-medium capitalize"
                      style={{
                        backgroundColor: f.status === 'recognized' ? 'rgba(39,166,68,0.12)' : 'rgba(245,158,11,0.12)',
                        color: f.status === 'recognized' ? '#27a644' : '#f59e0b',
                      }}
                    >
                      {f.status}
                    </span>
                  </div>
                  <p className="truncate" style={{ color: 'var(--th-text-quaternary)' }}>{f.format_fingerprint}</p>
                  <p className="mt-0.5" style={{ color: 'var(--th-text-quaternary)' }}>
                    {f.sample_count} sample{f.sample_count !== 1 ? 's' : ''} · Last seen {fmtDate(f.last_seen)}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Invoice History */}
      <div className="rounded-lg" style={{ backgroundColor: 'var(--th-surface-0)', border: '1px solid var(--th-border)' }}>
        <div className="flex items-center justify-between px-5 py-4" style={{ borderBottom: '1px solid var(--th-border)' }}>
          <h2 className="text-sm font-semibold flex items-center gap-2" style={{ color: 'var(--th-text-primary)' }}>
            <FileText className="h-4 w-4" style={{ color: 'var(--th-accent)' }} />
            Invoice History
            <span className="text-xs font-normal" style={{ color: 'var(--th-text-quaternary)' }}>({invoices.length})</span>
          </h2>
          <button onClick={() => setInvoiceSortAsc(!invoiceSortAsc)} className="text-xs" style={{ color: 'var(--th-text-tertiary)' }}>
            {invoiceSortAsc ? 'Oldest first' : 'Newest first'}
          </button>
        </div>
        {sortedInvoices.length === 0 ? (
          <p className="py-8 text-center text-sm" style={{ color: 'var(--th-text-tertiary)' }}>No invoices for this vendor</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr style={{ borderBottom: '1px solid var(--th-border)' }}>
                  <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider" style={{ color: 'var(--th-text-quaternary)' }}>Invoice</th>
                  <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider hidden sm:table-cell" style={{ color: 'var(--th-text-quaternary)' }}>Period</th>
                  <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider hidden sm:table-cell" style={{ color: 'var(--th-text-quaternary)' }}>Due Date</th>
                  <th className="px-4 py-2.5 text-right text-xs font-semibold uppercase tracking-wider" style={{ color: 'var(--th-text-quaternary)' }}>Amount</th>
                  <th className="px-4 py-2.5 text-center text-xs font-semibold uppercase tracking-wider" style={{ color: 'var(--th-text-quaternary)' }}>Status</th>
                  <th className="px-4 py-2.5 text-center text-xs font-semibold uppercase tracking-wider" style={{ color: 'var(--th-text-quaternary)' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {sortedInvoices.map((inv) => {
                  const ss = STATUS_STYLES[inv.status] || STATUS_STYLES.received;
                  return (
                    <tr key={inv.id} className="transition-colors hover:bg-[var(--th-hover)]" style={{ borderBottom: '1px solid var(--th-border)' }}>
                      <td className="px-4 py-3">
                        <InvoiceNumberLink
                          invoiceId={inv.id}
                          pdfPath={inv.pdf_path}
                          onOpen={(id, path) => setViewerInvoice({ id, pdf_path: path })}
                        />
                      </td>
                      <td className="px-4 py-3 hidden sm:table-cell" style={{ color: 'var(--th-text-tertiary)' }}>{inv.billing_period || '—'}</td>
                      <td className="px-4 py-3 hidden sm:table-cell" style={{ color: 'var(--th-text-tertiary)' }}>{fmtDate(inv.due_date)}</td>
                      <td className="px-4 py-3 text-right font-medium" style={{ color: 'var(--th-text-primary)' }}>
                        {currency(inv.outstanding_balance ?? 0)}
                      </td>
                      <td className="px-4 py-3 text-center">
                        <span className="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium capitalize" style={{ backgroundColor: ss.bg, color: ss.text, border: `1px solid ${ss.border}` }}>
                          {inv.status.replace(/_/g, ' ')}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-center">
                        <div className="inline-flex items-center gap-1">
                          {canRegress(inv.status) && (
                            <button
                              onClick={() => statusMut.mutate({ id: inv.id, status: prevStatus[inv.status] as InvoiceStatus })}
                              className="rounded px-1.5 py-0.5 text-[10px] font-medium"
                              style={{ border: '1px solid var(--th-border)', color: 'var(--th-text-tertiary)' }}
                              title={`Move to ${prevStatus[inv.status]}`}
                            >←</button>
                          )}
                          {canAdvance(inv.status) && (
                            <button
                              onClick={() => statusMut.mutate({ id: inv.id, status: statusFlow[inv.status] as InvoiceStatus })}
                              className="rounded px-1.5 py-0.5 text-[10px] font-medium"
                              style={{ border: '1px solid var(--th-border)', color: 'var(--th-accent)' }}
                              title={`Advance to ${statusFlow[inv.status]}`}
                            >
                              {statusFlow[inv.status] === 'paid' ? <Check className="h-3 w-3" /> : '→'}
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {viewerInvoice && (
        <DocumentViewer
          invoiceId={viewerInvoice.id}
          pdfPath={viewerInvoice.pdf_path}
          onClose={() => setViewerInvoice(null)}
        />
      )}
    </div>
  );
}

function MiniCard({ icon, color, label, value }: { icon: React.ReactNode; color: string; label: string; value: string }) {
  return (
    <div className="rounded-lg p-3" style={{ backgroundColor: 'var(--th-surface-1)', border: '1px solid var(--th-border)' }}>
      <div className="flex items-center gap-2">
        <div className="flex h-8 w-8 items-center justify-center rounded" style={{ backgroundColor: `${color}18`, color }}>{icon}</div>
        <div>
          <p className="text-[10px] uppercase tracking-wider" style={{ color: 'var(--th-text-quaternary)' }}>{label}</p>
          <p className="text-sm font-bold" style={{ color: 'var(--th-text-primary)' }}>{value}</p>
        </div>
      </div>
    </div>
  );
}