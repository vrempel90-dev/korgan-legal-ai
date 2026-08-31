import { readFileSync, writeFileSync } from 'node:fs';

function replaceRequired(text, from, to, label) {
  const index = text.indexOf(from);
  if (index < 0) throw new Error(`KORGAN ${label} not found; refusing to patch build.`);
  return text.slice(0, index) + to + text.slice(index + from.length);
}

const file = new URL('../src/main.jsx', import.meta.url);
let source = readFileSync(file, 'utf8');

const from = `  const uploadDocReceipt = async event => {
    const file = event.target.files?.[0]; event.target.value = ''; if (!file || !docPayment || receiptBusy) return;
    setReceiptBusy(true); setNotice('');
    try { const result = await korganApi.uploadDocumentReceipt(docPayment.order_id, file); setDocPayment(result.payment); setNotice(result.message || t.waitingAdmin); }
    catch (error) { setNotice(error?.message || t.down); } finally { setReceiptBusy(false); }
  };`;

const to = `  const uploadDocReceipt = async event => {
    const file = event.target.files?.[0]; event.target.value = ''; if (!file || !docPayment || receiptBusy) return;
    setReceiptBusy(true); setNotice(''); startGenerationProgress();
    try {
      const result = await korganApi.uploadDocumentReceipt(docPayment.order_id, file);
      if (result?.document_base64 || result?.filename || result?.paid === true) {
        setDocumentResult(result);
        setDocPayment(null);
        setActiveCase(prev => prev ? ({ ...prev, status: result.status || 'document_ready', title: result.title || prev.title, verification_status: result.verification_status, has_document: Boolean(result.document_base64 || result.filename), filing_ready: result.filing_ready, release_status: result.release_status }) : prev);
        await refreshCases();
        stopGenerationProgress();
        setScreen('ready');
        return;
      }
      stopGenerationProgress();
      setDocPayment(result?.payment || docPayment);
      setNotice(result?.message || t.paymentApproved);
    } catch (error) {
      stopGenerationProgress();
      setNotice(error?.message || t.down);
    } finally {
      setReceiptBusy(false);
    }
  };`;

source = replaceRequired(source, from, to, 'receipt-driven generation progress');
writeFileSync(file, source, 'utf8');
