import { useState, useMemo } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import {
  FileText,
  Search,
  X,
  ChevronDown,
  ChevronUp,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  Check,
  Download,
  RefreshCw,
  Filter,
  MoreHorizontal,
  Building2,
} from 'lucide-react';
import {
  getInvoices,
  getVendors,
  updateInvoiceStatus,
  bulkUpdateStatus,
  type DBInvoice,
  type InvoiceFilters,
  STATUS_STYLES,
  VALID_STATUSES,
  type InvoiceStatus,
} from '../lib/api';

const currency = (v: string | number) =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(
    typeof v === 'string' ? parseFloat(v) : v,
  );

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

type SortField = 'vendor_name' | 'billing_period' | 'due_date' | 'outstanding_balance' | 'status' | 'created_at';
type SortDir = 'asc' | 'desc';

export default function Invoices() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' } | null>(null);
  const showToast = (message: string, type: 'success' | 'error') => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 5000);
  };

  const [filtersOpen, setFiltersOpen] = useState(true);
  const [search, setSearch] = useState('');
  const [vendorFilter, setVendorFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [dueFrom, setDueFrom] = useState('');
  const [dueTo, setDueTo] = useState('');
  const [sortField, setSortField] = useState<SortField>('created_at');
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [hoveredRow, setHoveredRow] = useState<string | null>(null);
  const [openActionMenu, setOpenActionMenu] = useState<string | null>(null);

  const queryParams: InvoiceFilters = useMemo(() => ({
    search: search || undefined,
    vendor: vendorFilter || undefined,
    status: statusFilter || undefined,
    due_from: dueFrom || undefined,
    due_to: dueTo || undefined,
    sort_field: sortField,
    sort_dir: sortDir,
  }), [search, vendorFilter, statusFilter, dueFrom, dueTo, sortField, sortDir]);

  const { data: invoices = [], isLoading } = useQuery({
    queryKey: ['invoices', queryParams],
    queryFn: () => getInvoices(queryParams),
  });

  const { data: vendors = [] } = useQuery({
    queryKey: ['vendors'],
    queryFn: getVendors,
  });

  const statusMut = useMutation({
    mutationFn: ({ id, status }: { id: string; status: InvoiceStatus }) => updateInvoiceStatus(id, status),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['invoices'] });
      qc.invalidateQueries({ queryKey: ['dashboard'] });
    },
    onError: (e: Error) => showToast(`Failed: ${e.message}`, 'error'),
  });

  const bulkMut = useMutation({
    mutationFn: ({ ids, status }: { ids: string[]; status: InvoiceStatus }) => bulkUpdateStatus(ids, status),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['invoices'] });
      qc.invalidateQueries({ queryKey: ['dashboard'] });
      showToast(`Updated ${data.updated} invoice${data.updated !== 1 ? 's' : ''}`, 'success');
      setSelected(new Set());
    },
    onError: (e: Error) => showToast(`Failed: ${e.message}`, 'error'),
  });

  const handleSort = (field: SortField) => {
    if (sortField === field) setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    else { setSortField(field); setSortDir('asc'); }
  };

  const toggleSelect = (id: string) => setSelected(prev => {
    const next = new Set(prev);
    next.has(id) ? next.delete(id) : next.add(id);
    return next;
  });

  const toggleSelectAll = () => setSelected(prev =>
    prev.size === invoices.length ? new Set() : new Set(invoices.map(i => i.id)),
  );

  const clearFilters = () => {
    setSearch('');
    setVendorFilter('');
    setStatusFilter('');
    setDueFrom('');
    setDueTo('');
  };

  const SortIcon = ({ field }: { field: SortField }) => {
    if (sortField !== field) return <ArrowUpDown className="ml-1 h-3 w-3 opacity-40" />;
    return sortDir === 'asc' ? <ArrowUp className="ml-1 h-3 w-3" /> : <ArrowDown className="ml-1 h-3 w-3" />;
  };

  const exportCsv = () => {
    const headers = ['Invoice ID', 'Vendor', 'Billing Period', 'Due Date', 'Outstanding', 'Status'];
    const rows = invoices.map(i => [i.id, i.vendor_name || '', i.billing_period || '', i.due_date || '', String(i.outstanding_balance ?? 0), i.status]);
    const csv = [headers, ...rows].map(r => r.map(c => `"${c.replace(/"/g, '""')}"`).join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = 'invoices.csv'; a.click();
    URL.revokeObjectURL(url);
  };

  const inputCls = 'w-full rounded px-3 py-1.5 text-sm focus:outline-none';
  const selectCls = inputCls + ' appearance-none';
  const thCls = 'px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider cursor-pointer select-none whitespace-nowrap';

  const bulkActionBar = () => {
    if (selected.size === 0) return null;
    return (
      <div className="mb-3 flex flex-wrap items-center gap-2 rounded px-4 py-2" style={{ backgroundColor: 'rgba(57,216,189,0.08)', border: '1px solid rgba(57,216,189,0.2)' }}>
        <span className="text-xs font-medium" style={{ color: 'var(--th-accent)' }}>
          {selected.size} selected
        </span>
        <div className="flex-1" />
        {VALID_STATUSES.map(s => (
          <button
            key={s}
            onClick={() => bulkMut.mutate({ ids: Array.from(selected), status: s })}
            disabled={bulkMut.isPending}
            className="inline-flex items-center rounded px-2 py-1 text-xs font-medium disabled:opacity-40 transition-colors"
            style={{
              backgroundColor: STATUS_STYLES[s].bg,
              color: STATUS_STYLES[s].text,
              border: `1px solid ${STATUS_STYLES[s].border}`,
            }}
          >
            {s === 'paid' && <Check className="mr-1 h-3 w-3" />}
            Mark {s}
          </button>
        ))}
        <button
          onClick={() => setSelected(new Set())}
          className="text-xs px-2 py-1 rounded"
          style={{ color: 'var(--th-text-tertiary)' }}
        >
          <X className="h-3 w-3" />
        </button>
      </div>
    );
  };

  return (
    <div className="min-h-full p-3 sm:p-6" style={{ backgroundColor: 'var(--th-surface-2)', color: 'var(--th-text-primary)' }}>
      {/* Header */}
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-lg font-bold sm:text-xl" style={{ color: 'var(--th-accent)' }}>Invoices</h1>
          <p className="text-sm" style={{ color: 'var(--th-text-tertiary)' }}>{invoices.length} invoice{invoices.length !== 1 ? 's' : ''}</p>
        </div>
        <button onClick={() => qc.invalidateQueries({ queryKey: ['invoices'] })} className="inline-flex items-center rounded px-3 py-2 text-sm font-medium" style={{ backgroundColor: 'var(--th-surface-0)', color: 'var(--th-text-secondary)', border: '1px solid var(--th-border-strong)' }}>
          <RefreshCw className="h-4 w-4" />
        </button>
      </div>

      {/* Filters */}
      <div className="mb-3 rounded" style={{ backgroundColor: 'var(--th-surface-3)', border: '1px solid var(--th-border-strong)' }}>
        <button onClick={() => setFiltersOpen(o => !o)} className="flex w-full items-center justify-between px-4 py-2.5 text-sm font-medium" style={{ color: 'var(--th-text-secondary)' }}>
          <span className="flex items-center gap-2"><Filter className="h-4 w-4" /> Filters</span>
          {filtersOpen ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        </button>
        {filtersOpen && (
          <div className="px-4 py-4" style={{ borderTop: '1px solid var(--th-border-strong)' }}>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
              <div>
                <label className="mb-1 block text-xs" style={{ color: 'var(--th-text-tertiary)' }}>Search</label>
                <div className="relative">
                  <Search className="absolute left-2.5 top-2 h-3.5 w-3.5" style={{ color: 'var(--th-text-quaternary)' }} />
                  <input className={inputCls + ' pl-8'} placeholder="Invoice ID or period..." value={search} onChange={e => setSearch(e.target.value)} />
                </div>
              </div>
              <div>
                <label className="mb-1 block text-xs" style={{ color: 'var(--th-text-tertiary)' }}>Vendor</label>
                <select className={selectCls} value={vendorFilter} onChange={e => setVendorFilter(e.target.value)}>
                  <option value="">All Vendors</option>
                  {vendors.map(v => <option key={v.id} value={v.name}>{v.name}</option>)}
                </select>
              </div>
              <div>
                <label className="mb-1 block text-xs" style={{ color: 'var(--th-text-tertiary)' }}>Status</label>
                <select className={selectCls} value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
                  <option value="">All Statuses</option>
                  {VALID_STATUSES.map(s => (
                    <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="mb-1 block text-xs" style={{ color: 'var(--th-text-tertiary)' }}>Due From</label>
                <input type="date" className={inputCls} value={dueFrom} onChange={e => setDueFrom(e.target.value)} />
              </div>
              <div>
                <label className="mb-1 block text-xs" style={{ color: 'var(--th-text-tertiary)' }}>Due To</label>
                <input type="date" className={inputCls} value={dueTo} onChange={e => setDueTo(e.target.value)} />
              </div>
              <div className="flex items-end gap-2">
                <button onClick={clearFilters} className="inline-flex items-center rounded px-3 py-1.5 text-sm" style={{ border: '1px solid var(--th-border-strong)', color: 'var(--th-text-secondary)' }}>
                  <X className="mr-1 h-3.5 w-3.5" /> Clear
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Bulk action bar */}
      {bulkActionBar()}

      {/* Action bar */}
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded px-3 py-2 sm:px-4" style={{ backgroundColor: 'var(--th-surface-3)', border: '1px solid var(--th-border-strong)' }}>
        <div className="flex items-center gap-2">
          <button onClick={exportCsv} className="inline-flex items-center rounded px-2.5 py-1 text-xs" style={{ border: '1px solid var(--th-border-strong)', color: 'var(--th-text-secondary)' }}>
            <Download className="mr-1 h-3.5 w-3.5" /> CSV
          </button>
        </div>
      </div>

      {/* Table */}
      <div className="overflow-hidden rounded" style={{ backgroundColor: 'var(--th-surface-3)', border: '1px solid var(--th-border-strong)' }}>
        {isLoading ? (
          <div className="flex justify-center py-16">
            <div className="h-8 w-8 animate-spin rounded-full border-4 border-brand border-t-transparent" />
          </div>
        ) : invoices.length === 0 ? (
          <div className="py-16 text-center">
            <FileText className="mx-auto h-10 w-10" style={{ color: 'var(--th-text-quaternary)' }} />
            <p className="mt-3 text-sm" style={{ color: 'var(--th-text-tertiary)' }}>No invoices found</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full" style={{ borderCollapse: 'separate', borderSpacing: 0 }}>
              <thead style={{ backgroundColor: 'var(--th-surface-2)' }}>
                <tr>
                  <th className="w-10 px-4 py-2.5">
                    <input type="checkbox" checked={selected.size === invoices.length && invoices.length > 0} onChange={toggleSelectAll} className="rounded" />
                  </th>
                  <th className={thCls} onClick={() => handleSort('vendor_name')}>
                    <span className="inline-flex items-center">Vendor <SortIcon field="vendor_name" /></span>
                  </th>
                  <th className={thCls + ' hidden sm:table-cell'} onClick={() => handleSort('billing_period')}>
                    <span className="inline-flex items-center">Period <SortIcon field="billing_period" /></span>
                  </th>
                  <th className={thCls + ' hidden sm:table-cell'} onClick={() => handleSort('due_date')}>
                    <span className="inline-flex items-center">Due Date <SortIcon field="due_date" /></span>
                  </th>
                  <th className={thCls} onClick={() => handleSort('outstanding_balance')}>
                    <span className="inline-flex items-center">Amount <SortIcon field="outstanding_balance" /></span>
                  </th>
                  <th className={thCls} onClick={() => handleSort('status')}>
                    <span className="inline-flex items-center">Status <SortIcon field="status" /></span>
                  </th>
                  <th className="px-4 py-2.5 text-center text-xs font-semibold uppercase tracking-wider" style={{ color: 'var(--th-text-tertiary)' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {invoices.map((inv) => {
                  const ss = STATUS_STYLES[inv.status] || STATUS_STYLES.received;
                  return (
                    <tr
                      key={inv.id}
                      className="transition-colors"
                      style={{
                        borderBottom: '1px solid var(--th-border)',
                        backgroundColor: selected.has(inv.id) ? 'rgba(57,216,189,0.08)' : hoveredRow === inv.id ? 'var(--th-hover)' : undefined,
                      }}
                      onMouseEnter={() => setHoveredRow(inv.id)}
                      onMouseLeave={() => { setHoveredRow(null); setOpenActionMenu(null); }}
                    >
                      <td className="px-4 py-2.5">
                        <input type="checkbox" checked={selected.has(inv.id)} onChange={() => toggleSelect(inv.id)} className="rounded" />
                      </td>
                      <td className="whitespace-nowrap px-4 py-2.5 text-sm">
                        <button
                          onClick={() => navigate(`/vendors/${inv.vendor_id}`)}
                          className="inline-flex items-center gap-1.5 hover:underline"
                          style={{ color: 'var(--th-accent)' }}
                        >
                          <Building2 className="h-3 w-3" />
                          {inv.vendor_name || 'Unknown'}
                        </button>
                      </td>
                      <td className="hidden whitespace-nowrap px-4 py-2.5 text-sm sm:table-cell" style={{ color: 'var(--th-text-secondary)' }}>
                        {inv.billing_period || '—'}
                      </td>
                      <td className="hidden whitespace-nowrap px-4 py-2.5 text-sm sm:table-cell" style={{ color: 'var(--th-text-secondary)' }}>
                        {fmtDate(inv.due_date)}
                      </td>
                      <td className="whitespace-nowrap px-4 py-2.5 text-sm font-medium" style={{ color: 'var(--th-text-primary)' }}>
                        {currency(inv.outstanding_balance ?? 0)}
                      </td>
                      <td className="whitespace-nowrap px-4 py-2.5">
                        <span
                          className="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium capitalize"
                          style={{ backgroundColor: ss.bg, color: ss.text, border: `1px solid ${ss.border}` }}
                        >
                          {inv.status.replace(/_/g, ' ')}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-center relative">
                        <div className="inline-flex items-center gap-1">
                          {canRegress(inv.status) && (
                            <button
                              onClick={() => statusMut.mutate({ id: inv.id, status: prevStatus[inv.status] as InvoiceStatus })}
                              disabled={statusMut.isPending}
                              className="rounded px-1.5 py-0.5 text-[10px] font-medium transition-colors"
                              style={{ border: '1px solid var(--th-border)', color: 'var(--th-text-tertiary)' }}
                              title={`Move to ${prevStatus[inv.status]}`}
                            >
                              ←
                            </button>
                          )}
                          {canAdvance(inv.status) && (
                            <button
                              onClick={() => statusMut.mutate({ id: inv.id, status: statusFlow[inv.status] as InvoiceStatus })}
                              disabled={statusMut.isPending}
                              className="rounded px-1.5 py-0.5 text-[10px] font-medium transition-colors"
                              style={{ border: '1px solid var(--th-border)', color: 'var(--th-accent)' }}
                              title={`Advance to ${statusFlow[inv.status]}`}
                            >
                              {statusFlow[inv.status] === 'paid' ? <Check className="h-3 w-3" /> : '→'}
                            </button>
                          )}
                          <button
                            onClick={() => setOpenActionMenu(openActionMenu === inv.id ? null : inv.id)}
                            className="rounded p-1"
                            style={{ color: 'var(--th-text-quaternary)' }}
                          >
                            <MoreHorizontal className="h-3.5 w-3.5" />
                          </button>
                        </div>
                        {openActionMenu === inv.id && (
                          <div
                            className="absolute right-0 top-full z-10 mt-1 w-40 rounded-lg shadow-lg py-1"
                            style={{ backgroundColor: 'var(--th-surface-0)', border: '1px solid var(--th-border-strong)' }}
                          >
                            {VALID_STATUSES.filter(s => s !== inv.status).map(s => (
                              <button
                                key={s}
                                onClick={() => { statusMut.mutate({ id: inv.id, status: s }); setOpenActionMenu(null); }}
                                className="w-full text-left px-3 py-1.5 text-xs hover:bg-[var(--th-hover)] flex items-center gap-2"
                                style={{ color: 'var(--th-text-secondary)' }}
                              >
                                <span className="inline-block w-2 h-2 rounded-full" style={{ backgroundColor: STATUS_STYLES[s].text }} />
                                {s.replace(/_/g, ' ')}
                              </button>
                            ))}
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Toast */}
      {toast && (
        <div className="fixed bottom-4 right-4 z-50">
          <div className={`rounded-lg px-4 py-3 shadow-lg ${toast.type === 'success' ? 'bg-green-600' : 'bg-red-600'} text-white text-sm`}>
            {toast.message}
          </div>
        </div>
      )}
    </div>
  );
}