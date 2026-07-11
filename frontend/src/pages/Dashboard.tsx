import { useState, useEffect, useRef, useCallback } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  getVendors, getInvoicesBulk, getSummary, getInvoiceRawText, deleteInvoice, updateInvoice, uploadInvoice,
  type Invoice, type Customer, type LineItem,
} from '../lib/api';
import type { InvoiceFilters } from '../lib/api';
import { useAuth } from '../hooks/useAuth';
import { Chart, registerables } from 'chart.js';

Chart.register(...registerables);

function fmtMoney(n: number) {
  const sign = n < 0 ? '-' : '';
  return sign + '$' + Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function escHtml(s: string) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

export default function Dashboard() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [filters, setFilters] = useState<InvoiceFilters>({});
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState('');
  const [customerFilter, setCustomerFilter] = useState('');
  const [customerSearch, setCustomerSearch] = useState('');
  const [lineSearch, setLineSearch] = useState('');
  const [linePage, setLinePage] = useState(0);
  const LINE_PER_PAGE = 50;
  const [detailInvoiceId, setDetailInvoiceId] = useState<string | null>(null);
  const [detailTab, setDetailTab] = useState<'parsed' | 'raw'>('parsed');
  const [saveStatus, setSaveStatus] = useState('');
  const [rawText, setRawText] = useState('');

  const customerChartRef = useRef<HTMLCanvasElement>(null);
  const categoryChartRef = useRef<HTMLCanvasElement>(null);
  const trendChartRef = useRef<HTMLCanvasElement>(null);
  const customerChartInst = useRef<Chart | null>(null);
  const categoryChartInst = useRef<Chart | null>(null);
  const trendChartInst = useRef<Chart | null>(null);

  const { data: vendors = [] } = useQuery({ queryKey: ['vendors'], queryFn: getVendors });
  const { data: bulkResp } = useQuery({
    queryKey: ['invoices-bulk', filters],
    queryFn: () => getInvoicesBulk(filters),
  });
  const invoices = bulkResp?.invoices || [];

  // Sync selectedIds with loaded invoices
  useEffect(() => {
    if (invoices.length > 0) {
      setSelectedIds((prev) => {
        const ids = new Set(invoices.map((i) => i.id));
        // Keep only IDs that exist in current data
        const filtered = new Set([...prev].filter((id) => ids.has(id)));
        return filtered.size > 0 ? filtered : ids;
      });
    }
  }, [invoices]);

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteInvoice(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['invoices-bulk'] }),
  });

  // Derived data
  const filteredInvoices = invoices.filter((inv) => selectedIds.has(inv.id));
  const filteredCustomers = (() => {
    const map = new Map<string, Customer>();
    filteredInvoices.forEach((inv) =>
      inv.customers.forEach((c) => {
        const key = c.name + '|' + c.account_id;
        const existing = map.get(key);
        if (existing) existing.total += c.total;
        else map.set(key, { ...c });
      })
    );
    let arr = [...map.values()];
    if (customerFilter) arr = arr.filter((c) => c.name === customerFilter);
    if (customerSearch) {
      const q = customerSearch.toLowerCase();
      arr = arr.filter((c) => c.name.toLowerCase().includes(q) || c.account_id.toLowerCase().includes(q));
    }
    return arr;
  })();
  const filteredLineItems = (() => {
    let items: LineItem[] = [];
    filteredInvoices.forEach((inv) => inv.line_items.forEach((li) => items.push({ ...li, invoice_id: inv.id })));
    if (customerFilter) items = items.filter((li) => li.customer_name === customerFilter);
    if (lineSearch) {
      const q = lineSearch.toLowerCase();
      items = items.filter((li) => li.customer_name.toLowerCase().includes(q) || li.item.toLowerCase().includes(q));
    }
    return items;
  })();
  const summary = (() => {
    let prev = 0, pay = 0, nc = 0, out = 0, cc = 0;
    filteredInvoices.forEach((inv) => {
      prev += inv.summary.previous_balance;
      pay += inv.summary.payment_received;
      nc += inv.summary.new_charges;
      out += inv.summary.outstanding_balance;
      cc += inv.summary.credit_card_surcharges || 0;
    });
    return { previous_balance: prev, payment_received: pay, new_charges: nc, outstanding_balance: out, cc };
  })();
  const totalNewCharges = summary.new_charges;
  const allCustomerNames = [...new Set(invoices.flatMap((inv) => inv.customers.map((c) => c.name)))].sort();

  // Charts
  useEffect(() => {
    if (!customerChartRef.current || !categoryChartRef.current || !trendChartRef.current) return;
    // Customer bar chart
    const sorted = [...filteredCustomers].sort((a, b) => b.total - a.total).slice(0, 10);
    if (customerChartInst.current) customerChartInst.current.destroy();
    customerChartInst.current = new Chart(customerChartRef.current, {
      type: 'bar',
      data: {
        labels: sorted.map((c) => c.name.length > 22 ? c.name.substring(0, 22) + '…' : c.name),
        datasets: [{ data: sorted.map((c) => c.total), backgroundColor: ['#3b82f6', '#8b5cf6', '#14b8a6', '#f59e0b', '#ef4444', '#ec4899', '#6366f1', '#84cc16', '#06b6d4', '#f97316'], borderRadius: 6 }],
      },
      options: { indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { ticks: { color: '#9cadb8' } }, y: { ticks: { color: '#9cadb8', font: { size: 11 } }, grid: { display: false } } } },
    });

    // Category doughnut
    const cats: Record<string, number> = {};
    filteredLineItems.forEach((li) => {
      let cat = 'Other';
      const item = li.item.toLowerCase();
      if (item.includes('microsoft 365') || item.includes('office 365') || item.includes('office apps')) cat = 'Microsoft 365';
      else if (item.includes('exchange') || item.includes('email')) cat = 'Email';
      else if (item.includes('elevate') || item.includes('voicemail') || item.includes('toll-free') || item.includes('surcharge')) cat = 'Voice';
      else if (item.includes('yealink') || item.includes('hardware') || item.includes('shipping')) cat = 'Hardware';
      else if (item.includes('tax') || item.includes('e-911') || item.includes('fusf')) cat = 'Taxes & Fees';
      else if (item.includes('storage') || item.includes('archiv')) cat = 'Storage';
      else if (item.includes('security') || item.includes('azure')) cat = 'Security';
      if (li.type === 'credit') cat = 'Credits';
      cats[cat] = (cats[cat] || 0) + li.amount;
    });
    const catLabels = Object.keys(cats).sort((a, b) => cats[b] - cats[a]);
    if (categoryChartInst.current) categoryChartInst.current.destroy();
    categoryChartInst.current = new Chart(categoryChartRef.current, {
      type: 'doughnut',
      data: { labels: catLabels, datasets: [{ data: catLabels.map((l) => cats[l]), backgroundColor: ['#3b82f6', '#8b5cf6', '#14b8a6', '#f59e0b', '#ef4444', '#ec4899', '#6366f1', '#84cc16', '#06b6d4', '#f97316', '#a78bfa'], borderColor: '#1a1d27', borderWidth: 2 }] },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'right', labels: { color: '#9cadb8', font: { size: 12 }, boxWidth: 12 } } } },
    });

    // Monthly trend
    const monthly: Record<string, number> = {};
    filteredInvoices.forEach((inv) => {
      const bp = inv.billing_period || '';
      let mk = bp;
      if (/^\d{4}-\d{2}/.test(bp)) mk = bp.substring(0, 7);
      else { const d = new Date(bp); if (!isNaN(d.getTime())) mk = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0'); }
      monthly[mk] = (monthly[mk] || 0) + (inv.summary.new_charges || 0);
    });
    const mKeys = Object.keys(monthly).sort();
    if (trendChartInst.current) trendChartInst.current.destroy();
    trendChartInst.current = new Chart(trendChartRef.current, {
      type: 'line',
      data: { labels: mKeys, datasets: [{ label: 'Total Charges', data: mKeys.map((k) => monthly[k]), borderColor: '#3b82f6', backgroundColor: 'rgba(59,130,246,0.15)', fill: true, tension: 0.3, pointRadius: 3, pointBackgroundColor: '#3b82f6' }] },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { ticks: { color: '#9cadb8', font: { size: 11 } } }, y: { ticks: { color: '#9cadb8' } } } },
    });

    return () => {
      customerChartInst.current?.destroy();
      categoryChartInst.current?.destroy();
      trendChartInst.current?.destroy();
    };
  }, [filteredCustomers, filteredLineItems, filteredInvoices]);

  const uploadMutation = useMutation({
    mutationFn: ({ file, vendor }: { file: File; vendor: string }) => uploadInvoice(file, vendor),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['invoices-bulk'] }); queryClient.invalidateQueries({ queryKey: ['vendors'] }); },
  });

  const handleFileUpload = useCallback((files: FileList | null) => {
    if (!files) return;
    for (const file of Array.from(files)) {
      if (file.name.toLowerCase().endsWith('.pdf')) {
        uploadMutation.mutate({ file, vendor: filters.vendor || 'Unknown' });
      }
    }
  }, [uploadMutation, filters.vendor]);

  // Detail modal
  const detailInvoice = detailInvoiceId ? invoices.find((i) => i.id === detailInvoiceId) : null;

  const openDetail = useCallback(async (id: string) => {
    setDetailInvoiceId(id);
    setDetailTab('parsed');
    setSaveStatus('');
    try {
      const rt = await getInvoiceRawText(id);
      setRawText(rt.text);
    } catch { setRawText('(failed to load raw text)'); }
  }, []);

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!detailInvoiceId) return;
      const inv = invoices.find((i) => i.id === detailInvoiceId);
      if (!inv) return;
      const getVal = (id: string) => (document.getElementById(id) as HTMLInputElement)?.value || '';
      const getNum = (id: string) => parseFloat(getVal(id)) || 0;
      const invoiceData = {
        billing_period: getVal('edit_billing_period'),
        is_credit_memo: getVal('edit_is_credit_memo') === '1',
        references_invoice: getVal('edit_references') || null,
        partner_name: getVal('edit_partner_name'),
        partner_id: getVal('edit_partner_id'),
        partner_username: getVal('edit_partner_username'),
        previous_balance: getNum('edit_prev_balance'),
        credit_card_surcharges: getNum('edit_cc_surcharges'),
        payment_received: getNum('edit_payment'),
        new_charges: getNum('edit_new_charges'),
        outstanding_balance: getNum('edit_outstanding'),
      };
      const customers: Record<string, unknown>[] = [];
      document.querySelectorAll('#editCustomersBody tr').forEach((tr) => {
        const row = tr as HTMLTableRowElement;
        customers.push({
          name: (row.querySelector('.cust-name') as HTMLInputElement)?.value || '',
          account_id: (row.querySelector('.cust-acct') as HTMLInputElement)?.value || '',
          partner_id: (row.querySelector('.cust-partner') as HTMLInputElement)?.value || '',
          total: parseFloat((row.querySelector('.cust-total') as HTMLInputElement)?.value || '0') || 0,
        });
      });
      const lineItems: Record<string, unknown>[] = [];
      document.querySelectorAll('#editLineItemsBody tr').forEach((tr) => {
        const row = tr as HTMLTableRowElement;
        lineItems.push({
          customer_name: (row.querySelector('.li-customer') as HTMLInputElement)?.value || '',
          date: (row.querySelector('.li-date') as HTMLInputElement)?.value || '',
          item: (row.querySelector('.li-item') as HTMLInputElement)?.value || '',
          type: (row.querySelector('.li-type') as HTMLSelectElement)?.value || 'service',
          qty: parseInt((row.querySelector('.li-qty') as HTMLInputElement)?.value || '0') || 0,
          unit_price: parseFloat((row.querySelector('.li-unit-price') as HTMLInputElement)?.value || '0') || 0,
          amount: parseFloat((row.querySelector('.li-amount') as HTMLInputElement)?.value || '0') || 0,
        });
      });
      await updateInvoice(detailInvoiceId, { invoice: invoiceData, customers, line_items: lineItems });
    },
    onSuccess: () => {
      setSaveStatus('✓ Saved successfully');
      queryClient.invalidateQueries({ queryKey: ['invoices-bulk'] });
    },
    onError: (e: Error) => setSaveStatus(`✗ Error: ${e.message}`),
  });

  const paginatedLineItems = (() => {
    const totalPages = Math.max(1, Math.ceil(filteredLineItems.length / LINE_PER_PAGE));
    const page = Math.min(linePage, totalPages - 1);
    const start = page * LINE_PER_PAGE;
    return { items: filteredLineItems.slice(start, start + LINE_PER_PAGE), totalPages, page };
  })();

  return (
    <div className="min-h-full p-3 sm:p-6" style={{ backgroundColor: 'var(--th-surface-1)' }}>
      {/* Header */}
      <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
        <div>
          <h1 className="text-xl font-semibold" style={{ color: 'var(--th-text-primary)' }}>Vendor Invoice Dashboard</h1>
          <p className="text-sm" style={{ color: 'var(--th-text-tertiary)' }}>Oklahoma Technology Solutions · Partner ID 36024</p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-sm" style={{ color: 'var(--th-text-tertiary)' }}>{user?.full_name || user?.email}</span>
          {filters.vendor && <span className="px-3 py-1 rounded-md text-sm font-semibold text-white" style={{ background: 'linear-gradient(135deg, #3b82f6, #8b5cf6)' }}>{filters.vendor}</span>}
        </div>
      </div>

      {/* Filter Bar */}
      <div className="mb-4 p-4 rounded-panel" style={{ backgroundColor: 'var(--th-surface-0)', border: '1px solid var(--th-border)' }}>
        <div className="flex gap-3 flex-wrap items-end">
          <div className="flex-1 min-w-[160px]">
            <label className="block text-xs uppercase tracking-wider mb-1" style={{ color: 'var(--th-text-tertiary)' }}>Vendor</label>
            <select value={filters.vendor || ''} onChange={(e) => setFilters((f) => ({ ...f, vendor: e.target.value || undefined }))} className="w-full px-3 py-2 text-sm rounded-lg">
              <option value="">All Vendors</option>
              {vendors.map((v) => <option key={v.id} value={v.name}>{v.name}</option>)}
            </select>
          </div>
          <div className="flex-1 min-w-[160px]">
            <label className="block text-xs uppercase tracking-wider mb-1" style={{ color: 'var(--th-text-tertiary)' }}>Customer</label>
            <select value={customerFilter} onChange={(e) => setCustomerFilter(e.target.value)} className="w-full px-3 py-2 text-sm rounded-lg">
              <option value="">All Customers</option>
              {allCustomerNames.map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </div>
          <div className="flex-1 min-w-[160px]">
            <label className="block text-xs uppercase tracking-wider mb-1" style={{ color: 'var(--th-text-tertiary)' }}>Search</label>
            <input type="text" value={search} onChange={(e) => { setSearch(e.target.value); setFilters((f) => ({ ...f, search: e.target.value || undefined })); }} placeholder="Invoice ID or billing period..." className="w-full px-3 py-2 text-sm rounded-lg" />
          </div>
          <div className="min-w-[130px]">
            <label className="block text-xs uppercase tracking-wider mb-1" style={{ color: 'var(--th-text-tertiary)' }}>Start</label>
            <input type="date" value={filters.start || ''} onChange={(e) => setFilters((f) => ({ ...f, start: e.target.value || undefined }))} className="w-full px-3 py-2 text-sm rounded-lg" />
          </div>
          <div className="min-w-[130px]">
            <label className="block text-xs uppercase tracking-wider mb-1" style={{ color: 'var(--th-text-tertiary)' }}>End</label>
            <input type="date" value={filters.end || ''} onChange={(e) => setFilters((f) => ({ ...f, end: e.target.value || undefined }))} className="w-full px-3 py-2 text-sm rounded-lg" />
          </div>
          <div className="flex gap-2 items-end pb-0.5">
            <button onClick={() => setFilters({})} className="px-3 py-2 text-sm rounded-lg font-medium" style={{ backgroundColor: 'var(--th-surface-2)', color: 'var(--th-text-tertiary)', border: '1px solid var(--th-border)' }}>Clear</button>
          </div>
        </div>
        <div className="flex gap-4 mt-3 flex-wrap items-end">
          <div className="flex-1 min-w-[200px]">
            <label className="block text-xs uppercase tracking-wider mb-1" style={{ color: 'var(--th-text-tertiary)' }}>Invoices ({selectedIds.size} / {invoices.length})</label>
            <div className="max-h-[120px] overflow-y-auto rounded-lg p-1" style={{ backgroundColor: 'var(--th-surface-2)', border: '1px solid var(--th-border)' }}>
              {invoices.map((inv) => (
                <div key={inv.id} className="flex items-center gap-2 px-2 py-1 rounded cursor-pointer hover" style={{ backgroundColor: selectedIds.has(inv.id) ? 'var(--th-active)' : 'transparent' }}
                  onClick={() => setSelectedIds((prev) => { const n = new Set(prev); n.has(inv.id) ? n.delete(inv.id) : n.add(inv.id); return n; })}>
                  <span className="flex-1 text-sm truncate" style={{ color: selectedIds.has(inv.id) ? 'var(--th-text-primary)' : 'var(--th-text-secondary)' }}>
                    #{inv.id}{inv.is_credit_memo ? ' 📝' : ''} — {inv.billing_period}
                  </span>
                  <button onClick={(e) => { e.stopPropagation(); openDetail(inv.id); }} className="text-xs px-1.5 py-0.5 rounded" style={{ color: 'var(--th-text-tertiary)' }} title="View">👁</button>
                  <button onClick={(e) => { e.stopPropagation(); if (confirm(`Delete invoice #${inv.id}?`)) deleteMutation.mutate(inv.id); }} className="text-xs px-1.5 py-0.5 rounded" style={{ color: 'var(--th-text-tertiary)' }} title="Delete">✕</button>
                </div>
              ))}
            </div>
          </div>
          <div className="min-w-[200px]">
            <label className="block text-xs uppercase tracking-wider mb-1" style={{ color: 'var(--th-text-tertiary)' }}>Upload PDF</label>
            <div className="border-2 border-dashed rounded-lg p-3 text-center cursor-pointer text-sm" style={{ borderColor: 'var(--th-border)', color: 'var(--th-text-tertiary)' }}
              onClick={() => document.getElementById('pdfUpload')?.click()}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => { e.preventDefault(); handleFileUpload(e.dataTransfer.files); }}>
              📄 Drop PDF here or click to browse
              <input id="pdfUpload" type="file" accept=".pdf" multiple className="hidden" onChange={(e) => handleFileUpload(e.target.files)} />
            </div>
            {uploadMutation.isPending && <p className="text-xs mt-1" style={{ color: 'var(--th-text-tertiary)' }}>Uploading...</p>}
          </div>
          <div className="flex flex-col gap-1">
            <label className="block text-xs uppercase tracking-wider" style={{ color: 'var(--th-text-tertiary)' }}>Export</label>
            <a href={`/api/export/invoices?token=${localStorage.getItem('access_token')}`} className="px-3 py-1.5 text-sm rounded-lg text-center" style={{ backgroundColor: 'var(--th-surface-2)', color: 'var(--th-text-tertiary)', border: '1px solid var(--th-border)' }} download>📥 Export CSV</a>
          </div>
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-7 gap-3 mb-4">
        {[
          { label: 'Previous Balance', value: fmtMoney(summary.previous_balance), cls: '' },
          { label: 'Payment Received', value: fmtMoney(-summary.payment_received), cls: 'text-green' },
          { label: 'New Charges', value: fmtMoney(summary.new_charges), cls: 'text-warning' },
          { label: 'CC Surcharges', value: fmtMoney(summary.cc), cls: '' },
          { label: 'Outstanding Balance', value: fmtMoney(summary.outstanding_balance), cls: 'text-danger' },
          { label: 'Active Customers', value: filteredCustomers.length.toString(), cls: '' },
          { label: 'Selected', value: `${filteredInvoices.length} / ${invoices.length}`, cls: '' },
        ].map((c) => (
          <div key={c.label} className="p-3 rounded-card" style={{ backgroundColor: 'var(--th-surface-0)', border: '1px solid var(--th-border)' }}>
            <div className="text-xs uppercase tracking-wider" style={{ color: 'var(--th-text-tertiary)' }}>{c.label}</div>
            <div className={`text-lg font-bold mt-1 ${c.cls}`} style={{ color: c.cls ? undefined : 'var(--th-text-primary)' }}>{c.value}</div>
          </div>
        ))}
      </div>

      {/* Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-4">
        <div className="p-4 rounded-card" style={{ backgroundColor: 'var(--th-surface-0)', border: '1px solid var(--th-border)' }}>
          <h3 className="text-sm font-medium mb-3" style={{ color: 'var(--th-text-tertiary)' }}>Charges by Customer (Top 10)</h3>
          <div className="relative h-[260px]"><canvas ref={customerChartRef} /></div>
        </div>
        <div className="p-4 rounded-card" style={{ backgroundColor: 'var(--th-surface-0)', border: '1px solid var(--th-border)' }}>
          <h3 className="text-sm font-medium mb-3" style={{ color: 'var(--th-text-tertiary)' }}>Charges by Service Category</h3>
          <div className="relative h-[260px]"><canvas ref={categoryChartRef} /></div>
        </div>
        <div className="p-4 rounded-card lg:col-span-2" style={{ backgroundColor: 'var(--th-surface-0)', border: '1px solid var(--th-border)' }}>
          <h3 className="text-sm font-medium mb-3" style={{ color: 'var(--th-text-tertiary)' }}>Monthly Charges Trend</h3>
          <div className="relative h-[260px]"><canvas ref={trendChartRef} /></div>
        </div>
      </div>

      {/* Customer Table */}
      <div className="mb-4">
        <div className="flex items-center gap-2 mb-3">
          <h2 className="text-base font-semibold" style={{ color: 'var(--th-text-primary)' }}>Customer Accounts</h2>
          <span className="text-xs px-2 py-0.5 rounded-full" style={{ backgroundColor: 'var(--th-surface-2)', color: 'var(--th-text-tertiary)' }}>{filteredCustomers.length} accounts</span>
        </div>
        <input type="text" value={customerSearch} onChange={(e) => setCustomerSearch(e.target.value)} placeholder="Search customers..." className="w-full px-3 py-2 text-sm rounded-lg mb-2" style={{ backgroundColor: 'var(--th-surface-0)', border: '1px solid var(--th-border)' }} />
        <div className="overflow-x-auto rounded-card" style={{ border: '1px solid var(--th-border)' }}>
          <table className="w-full text-sm">
            <thead>
              <tr style={{ backgroundColor: 'var(--th-surface-0)' }}>
                {['Customer', 'Account ID', 'Partner Ref', 'Total Charges', '% of Total'].map((h) => (
                  <th key={h} className="px-3 py-2 text-left text-xs font-semibold uppercase" style={{ color: 'var(--th-text-tertiary)' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filteredCustomers.map((c, i) => (
                <tr key={i} style={{ borderTop: '1px solid var(--th-border)' }}>
                  <td className="px-3 py-2 font-medium" style={{ color: 'var(--th-text-primary)' }}>{c.name}</td>
                  <td className="px-3 py-2 font-mono text-xs" style={{ color: 'var(--th-text-tertiary)' }}>{c.account_id}</td>
                  <td className="px-3 py-2 font-mono text-xs" style={{ color: 'var(--th-text-tertiary)' }}>{c.partner_id}</td>
                  <td className="px-3 py-2 text-right font-semibold">{fmtMoney(c.total)}</td>
                  <td className="px-3 py-2 text-right" style={{ color: 'var(--th-text-tertiary)' }}>{totalNewCharges > 0 ? ((c.total / totalNewCharges) * 100).toFixed(1) : '0.0'}%</td>
                </tr>
              ))}
              {filteredCustomers.length === 0 && (
                <tr><td colSpan={5} className="px-3 py-8 text-center text-sm" style={{ color: 'var(--th-text-tertiary)' }}>No customers found.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Line Items Table */}
      <div className="mb-4">
        <div className="flex items-center gap-2 mb-3">
          <h2 className="text-base font-semibold" style={{ color: 'var(--th-text-primary)' }}>Line Items</h2>
          <span className="text-xs px-2 py-0.5 rounded-full" style={{ backgroundColor: 'var(--th-surface-2)', color: 'var(--th-text-tertiary)' }}>{filteredLineItems.length} items</span>
        </div>
        <input type="text" value={lineSearch} onChange={(e) => { setLineSearch(e.target.value); setLinePage(0); }} placeholder="Search line items..." className="w-full px-3 py-2 text-sm rounded-lg mb-2" style={{ backgroundColor: 'var(--th-surface-0)', border: '1px solid var(--th-border)' }} />
        <div className="overflow-x-auto rounded-card" style={{ border: '1px solid var(--th-border)' }}>
          <table className="w-full text-sm">
            <thead>
              <tr style={{ backgroundColor: 'var(--th-surface-0)' }}>
                {['Customer', 'Date', 'Service / Item', 'Type', 'Qty', 'Unit Price', 'Amount', 'Invoice'].map((h) => (
                  <th key={h} className="px-3 py-2 text-left text-xs font-semibold uppercase" style={{ color: 'var(--th-text-tertiary)' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {paginatedLineItems.items.map((li, i) => {
                const badgeCls = li.type === 'monthly' ? 'rgba(59,130,246,0.15)' : li.type === 'service_charge' ? 'rgba(139,92,246,0.15)' : li.type === 'tax' ? 'rgba(245,158,11,0.15)' : 'rgba(34,197,94,0.15)';
                return (
                  <tr key={i} style={{ borderTop: '1px solid var(--th-border)' }}>
                    <td className="px-3 py-2" style={{ color: 'var(--th-text-primary)' }}>{li.customer_name}</td>
                    <td className="px-3 py-2" style={{ color: 'var(--th-text-tertiary)' }}>{li.date}</td>
                    <td className="px-3 py-2">{li.item}</td>
                    <td className="px-3 py-2">
                      <span className="inline-block px-2 py-0.5 rounded-full text-xs font-semibold" style={{ backgroundColor: badgeCls, color: li.type === 'credit' ? '#4ade80' : 'var(--th-text-tertiary)' }}>
                        {li.type === 'monthly' ? 'Monthly' : li.type === 'service_charge' ? 'Service' : li.type === 'tax' ? 'Tax' : 'Credit'}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-right">{li.qty.toLocaleString()}</td>
                    <td className="px-3 py-2 text-right" style={{ color: 'var(--th-text-tertiary)' }}>{fmtMoney(li.unit_price)}</td>
                    <td className={`px-3 py-2 text-right font-semibold ${li.amount < 0 ? 'text-green' : ''}`}>{fmtMoney(li.amount)}</td>
                    <td className="px-3 py-2">
                      <button onClick={() => openDetail(li.invoice_id || '')} className="text-xs px-2 py-0.5 rounded-full font-semibold cursor-pointer" style={{ backgroundColor: 'rgba(20,184,166,0.15)', color: '#2dd4bf' }}>
                        #{li.invoice_id}
                      </button>
                    </td>
                  </tr>
                );
              })}
              {paginatedLineItems.items.length === 0 && (
                <tr><td colSpan={8} className="px-3 py-8 text-center text-sm" style={{ color: 'var(--th-text-tertiary)' }}>No line items found.</td></tr>
              )}
            </tbody>
          </table>
        </div>
        {filteredLineItems.length > LINE_PER_PAGE && (
          <div className="flex items-center justify-between mt-2">
            <span className="text-xs" style={{ color: 'var(--th-text-tertiary)' }}>Page {paginatedLineItems.page + 1} of {paginatedLineItems.totalPages} ({filteredLineItems.length} items)</span>
            <div className="flex gap-2">
              <button onClick={() => setLinePage((p) => Math.max(0, p - 1))} disabled={paginatedLineItems.page === 0} className="px-3 py-1 text-xs rounded-lg disabled:opacity-40" style={{ backgroundColor: 'var(--th-surface-2)', color: 'var(--th-text-tertiary)', border: '1px solid var(--th-border)' }}>← Prev</button>
              <button onClick={() => setLinePage((p) => Math.min(paginatedLineItems.totalPages - 1, p + 1))} disabled={paginatedLineItems.page >= paginatedLineItems.totalPages - 1} className="px-3 py-1 text-xs rounded-lg disabled:opacity-40" style={{ backgroundColor: 'var(--th-surface-2)', color: 'var(--th-text-tertiary)', border: '1px solid var(--th-border)' }}>Next →</button>
            </div>
          </div>
        )}
      </div>

      {/* Invoice Detail Modal */}
      {detailInvoice && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70" onClick={(e) => { if (e.target === e.currentTarget) setDetailInvoiceId(null); }}>
          <div className="flex flex-col rounded-panel w-[95vw] max-w-[1400px] h-[90vh]" style={{ backgroundColor: 'var(--th-bg)', border: '1px solid var(--th-border)' }}>
            <div className="flex items-center justify-between px-6 py-4 flex-shrink-0" style={{ borderBottom: '1px solid var(--th-border)' }}>
              <h2 className="text-base font-semibold" style={{ color: 'var(--th-text-primary)' }}>Invoice #{detailInvoice.id} — {detailInvoice.vendor}</h2>
              <button onClick={() => setDetailInvoiceId(null)} className="text-xl px-2 py-1 rounded" style={{ color: 'var(--th-text-tertiary)' }}>✕</button>
            </div>
            <div className="flex flex-1 overflow-hidden">
              {/* PDF Pane */}
              <div className="w-1/2 overflow-auto" style={{ borderRight: '1px solid var(--th-border)' }}>
                <iframe src={`/api/invoices/${detailInvoice.id}/pdf?token=${localStorage.getItem('access_token')}`} className="w-full h-full" title="PDF" />
              </div>
              {/* Data Pane */}
              <div className="w-1/2 overflow-auto p-6">
                <div className="flex gap-1 mb-4" style={{ borderBottom: '1px solid var(--th-border)' }}>
                  <button onClick={() => setDetailTab('parsed')} className="px-4 py-2 text-sm font-medium border-b-2 transition-colors" style={{ borderBottomColor: detailTab === 'parsed' ? 'var(--th-accent)' : 'transparent', color: detailTab === 'parsed' ? 'var(--th-accent)' : 'var(--th-text-tertiary)' }}>Parsed Data</button>
                  <button onClick={() => setDetailTab('raw')} className="px-4 py-2 text-sm font-medium border-b-2 transition-colors" style={{ borderBottomColor: detailTab === 'raw' ? 'var(--th-accent)' : 'transparent', color: detailTab === 'raw' ? 'var(--th-accent)' : 'var(--th-text-tertiary)' }}>Raw Text</button>
                </div>

                {detailTab === 'parsed' ? (
                  <div>
                    {/* Summary Section */}
                    <div className="mb-4 p-4 rounded-card" style={{ backgroundColor: 'var(--th-surface-0)', border: '1px solid var(--th-border)' }}>
                      <h4 className="text-sm font-semibold mb-3" style={{ color: 'var(--th-text-primary)' }}>Invoice Summary</h4>
                      <div className="grid grid-cols-2 gap-3">
                        {[
                          ['Billing Period', 'edit_billing_period', detailInvoice.billing_period],
                          ['Partner Name', 'edit_partner_name', detailInvoice.partner_name],
                          ['Partner ID', 'edit_partner_id', detailInvoice.partner_id],
                          ['Partner Username', 'edit_partner_username', detailInvoice.partner_username],
                          ['References Invoice', 'edit_references', detailInvoice.references_invoice || ''],
                        ].map(([label, id, val]) => (
                          <div key={id}>
                            <label className="block text-xs uppercase tracking-wider mb-1" style={{ color: 'var(--th-text-tertiary)' }}>{(label as string)}</label>
                            <input id={id as string} defaultValue={val as string} className="w-full px-2.5 py-2 text-sm rounded" />
                          </div>
                        ))}
                        <div>
                          <label className="block text-xs uppercase tracking-wider mb-1" style={{ color: 'var(--th-text-tertiary)' }}>Credit Memo?</label>
                          <select id="edit_is_credit_memo" defaultValue={detailInvoice.is_credit_memo ? '1' : '0'} className="w-full px-2.5 py-2 text-sm rounded">
                            <option value="0">No</option><option value="1">Yes</option>
                          </select>
                        </div>
                      </div>
                      <div className="grid grid-cols-3 gap-3 mt-3">
                        {[
                          ['Previous Balance', 'edit_prev_balance', detailInvoice.summary.previous_balance],
                          ['CC Surcharges', 'edit_cc_surcharges', detailInvoice.summary.credit_card_surcharges],
                          ['Payment Received', 'edit_payment', detailInvoice.summary.payment_received],
                          ['New Charges', 'edit_new_charges', detailInvoice.summary.new_charges],
                          ['Outstanding Balance', 'edit_outstanding', detailInvoice.summary.outstanding_balance],
                        ].map(([label, id, val]) => (
                          <div key={id}>
                            <label className="block text-xs uppercase tracking-wider mb-1" style={{ color: 'var(--th-text-tertiary)' }}>{(label as string)}</label>
                            <input id={id as string} type="number" step="0.01" defaultValue={val as number} className="w-full px-2.5 py-2 text-sm rounded" />
                          </div>
                        ))}
                      </div>
                    </div>

                    {/* Customers Section */}
                    <div className="mb-4 p-4 rounded-card" style={{ backgroundColor: 'var(--th-surface-0)', border: '1px solid var(--th-border)' }}>
                      <h4 className="text-sm font-semibold mb-3" style={{ color: 'var(--th-text-primary)' }}>Customers ({detailInvoice.customers.length})</h4>
                      <table className="w-full text-sm">
                        <thead>
                          <tr><th className="px-2 py-1 text-left text-xs font-semibold uppercase" style={{ color: 'var(--th-text-tertiary)' }}>Name</th><th className="px-2 py-1 text-left text-xs font-semibold uppercase" style={{ color: 'var(--th-text-tertiary)' }}>Account ID</th><th className="px-2 py-1 text-left text-xs font-semibold uppercase" style={{ color: 'var(--th-text-tertiary)' }}>Partner Ref</th><th className="px-2 py-1 text-right text-xs font-semibold uppercase" style={{ color: 'var(--th-text-tertiary)' }}>Total</th><th></th></tr>
                        </thead>
                        <tbody id="editCustomersBody">
                          {detailInvoice.customers.map((c, i) => (
                            <tr key={i}>
                              <td><input className="cust-name w-full px-2 py-1 text-xs rounded" defaultValue={c.name} /></td>
                              <td><input className="cust-acct w-full px-2 py-1 text-xs rounded" defaultValue={c.account_id} /></td>
                              <td><input className="cust-partner w-full px-2 py-1 text-xs rounded" defaultValue={c.partner_id} /></td>
                              <td><input className="cust-total w-full px-2 py-1 text-xs rounded text-right" type="number" step="0.01" defaultValue={c.total} /></td>
                              <td><button onClick={(e) => (e.currentTarget.closest('tr') as HTMLTableRowElement)?.remove()} className="text-xs px-1" style={{ color: 'var(--th-text-tertiary)' }}>✕</button></td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      <button onClick={() => {
                        const tb = document.getElementById('editCustomersBody');
                        if (!tb) return;
                        const tr = document.createElement('tr');
                        tr.innerHTML = `<td><input class="cust-name w-full px-2 py-1 text-xs rounded" /></td><td><input class="cust-acct w-full px-2 py-1 text-xs rounded" /></td><td><input class="cust-partner w-full px-2 py-1 text-xs rounded" /></td><td><input class="cust-total w-full px-2 py-1 text-xs rounded text-right" type="number" step="0.01" /></td><td><button onclick="this.closest('tr').remove()" class="text-xs px-1" style="color:var(--th-text-tertiary)">✕</button></td>`;
                        tb.appendChild(tr);
                      }} className="mt-2 text-xs px-3 py-1 rounded" style={{ border: '1px dashed var(--th-border)', color: 'var(--th-text-tertiary)' }}>+ Add Customer</button>
                    </div>

                    {/* Line Items Section */}
                    <div className="mb-4 p-4 rounded-card" style={{ backgroundColor: 'var(--th-surface-0)', border: '1px solid var(--th-border)' }}>
                      <h4 className="text-sm font-semibold mb-3" style={{ color: 'var(--th-text-primary)' }}>Line Items ({detailInvoice.line_items.length})</h4>
                      <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                          <thead>
                            <tr><th className="px-1 py-1 text-left text-xs font-semibold uppercase" style={{ color: 'var(--th-text-tertiary)' }}>Customer</th><th className="px-1 py-1 text-left text-xs font-semibold uppercase" style={{ color: 'var(--th-text-tertiary)' }}>Date</th><th className="px-1 py-1 text-left text-xs font-semibold uppercase" style={{ color: 'var(--th-text-tertiary)' }}>Item</th><th className="px-1 py-1 text-left text-xs font-semibold uppercase" style={{ color: 'var(--th-text-tertiary)' }}>Type</th><th className="px-1 py-1 text-right text-xs font-semibold uppercase" style={{ color: 'var(--th-text-tertiary)' }}>Qty</th><th className="px-1 py-1 text-right text-xs font-semibold uppercase" style={{ color: 'var(--th-text-tertiary)' }}>Price</th><th className="px-1 py-1 text-right text-xs font-semibold uppercase" style={{ color: 'var(--th-text-tertiary)' }}>Amt</th><th></th></tr>
                          </thead>
                          <tbody id="editLineItemsBody">
                            {detailInvoice.line_items.map((li, i) => (
                              <tr key={i}>
                                <td><input className="li-customer w-full px-1 py-1 text-xs rounded" defaultValue={li.customer_name} /></td>
                                <td><input className="li-date w-full px-1 py-1 text-xs rounded" defaultValue={li.date} /></td>
                                <td><input className="li-item w-full px-1 py-1 text-xs rounded" defaultValue={li.item} /></td>
                                <td><select className="li-type w-full px-1 py-1 text-xs rounded" defaultValue={li.type}>{[{v:'monthly',l:'Monthly'},{v:'service_charge',l:'Service'},{v:'tax',l:'Tax'},{v:'credit',l:'Credit'},{v:'service',l:'Service'},{v:'overage',l:'Overage'}].map((o) => <option key={o.v} value={o.v}>{o.l}</option>)}</select></td>
                                <td><input className="li-qty w-14 px-1 py-1 text-xs rounded text-right" type="number" defaultValue={li.qty} /></td>
                                <td><input className="li-unit-price w-20 px-1 py-1 text-xs rounded text-right" type="number" step="0.01" defaultValue={li.unit_price} /></td>
                                <td><input className="li-amount w-20 px-1 py-1 text-xs rounded text-right" type="number" step="0.01" defaultValue={li.amount} /></td>
                                <td><button onClick={(e) => (e.currentTarget.closest('tr') as HTMLTableRowElement)?.remove()} className="text-xs px-1" style={{ color: 'var(--th-text-tertiary)' }}>✕</button></td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                      <button onClick={() => {
                        const tb = document.getElementById('editLineItemsBody');
                        if (!tb) return;
                        const tr = document.createElement('tr');
                        tr.innerHTML = `<td><input class="li-customer w-full px-1 py-1 text-xs rounded" /></td><td><input class="li-date w-full px-1 py-1 text-xs rounded" /></td><td><input class="li-item w-full px-1 py-1 text-xs rounded" /></td><td><select class="li-type w-full px-1 py-1 text-xs rounded"><option value="service">Service</option></select></td><td><input class="li-qty w-14 px-1 py-1 text-xs rounded text-right" type="number" /></td><td><input class="li-unit-price w-20 px-1 py-1 text-xs rounded text-right" type="number" step="0.01" /></td><td><input class="li-amount w-20 px-1 py-1 text-xs rounded text-right" type="number" step="0.01" /></td><td><button onclick="this.closest('tr').remove()" class="text-xs px-1" style="color:var(--th-text-tertiary)">✕</button></td>`;
                        tb.appendChild(tr);
                      }} className="mt-2 text-xs px-3 py-1 rounded" style={{ border: '1px dashed var(--th-border)', color: 'var(--th-text-tertiary)' }}>+ Add Line Item</button>
                    </div>

                    {/* Save */}
                    <div className="flex items-center justify-between">
                      <span className={`text-xs ${saveStatus.includes('✓') ? 'text-green' : saveStatus.includes('✗') ? 'text-danger' : ''}`} style={{ color: saveStatus ? undefined : 'var(--th-text-tertiary)' }}>{saveStatus || ' '}</span>
                      <button onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending} className="px-6 py-2 text-sm font-semibold text-white rounded-lg disabled:opacity-50" style={{ backgroundColor: 'var(--color-brand)' }}>
                        {saveMutation.isPending ? 'Saving...' : 'Save Changes'}
                      </button>
                    </div>
                  </div>
                ) : (
                  <pre className="p-4 rounded-lg font-mono text-xs overflow-auto max-h-[calc(90vh-200px)] whitespace-pre-wrap" style={{ backgroundColor: 'var(--th-surface-2)', color: 'var(--th-text-tertiary)', border: '1px solid var(--th-border)' }}>
                    {rawText || '(loading...)'}
                  </pre>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Footer */}
      <div className="text-center text-xs py-4 mt-4" style={{ borderTop: '1px solid var(--th-border)', color: 'var(--th-text-quaternary)' }}>
        Vendor Invoice Dashboard · Data stored in SQLite · Powered by Flask
      </div>
    </div>
  );
}