import { readFileSync, writeFileSync } from 'node:fs';

function replaceRequired(text, from, to, label) {
  const index = text.indexOf(from);
  if (index < 0) throw new Error(`KORGAN ${label} not found; refusing to patch build.`);
  return text.slice(0, index) + to + text.slice(index + from.length);
}

const mainFile = new URL('../src/main.jsx', import.meta.url);
let source = readFileSync(mainFile, 'utf8');

source = replaceRequired(
  source,
  "  const [docPayment, setDocPayment] = useState(null);\n  const [adminOrders, setAdminOrders] = useState([]);",
  "  const [docPayment, setDocPayment] = useState(null);\n  const [generationProgress, setGenerationProgress] = useState(null);\n  const [adminOrders, setAdminOrders] = useState([]);",
  'generation progress state',
);

const helperAnchor = "  const generateDocument = async () => {";
const helper = `  useEffect(() => {
    if (!generationProgress?.startedAt) return undefined;
    const update = () => {
      const elapsed = Math.max(0, Math.floor((Date.now() - generationProgress.startedAt) / 1000));
      const stage = elapsed < 8 ? 0 : elapsed < 20 ? 1 : elapsed < 40 ? 2 : elapsed < 65 ? 3 : 4;
      setGenerationProgress(prev => prev ? { ...prev, elapsed, stage } : prev);
    };
    update();
    const timer = window.setInterval(update, 1000);
    return () => window.clearInterval(timer);
  }, [generationProgress?.startedAt]);

  const startGenerationProgress = () => setGenerationProgress({ startedAt: Date.now(), elapsed: 0, stage: 0 });
  const stopGenerationProgress = () => setGenerationProgress(null);

  const GenerationStatus = () => {
    if (!generationProgress) return null;
    const steps = language === 'kk'
      ? ['Материалдарды талдау', 'Құқық нормаларын тексеру', 'Құжат мәтінін дайындау', 'Қорытынды тексеру', 'Word құжатын жинау']
      : ['Анализ материалов', 'Проверка норм права', 'Подготовка текста документа', 'Финальная проверка', 'Сборка Word-документа'];
    const index = Math.max(0, Math.min(Number(generationProgress.stage || 0), steps.length - 1));
    const percent = [12, 32, 55, 78, 92][index];
    return <section className="generation-status-card" aria-live="polite" aria-atomic="true">
      <div className="generation-status-head">
        <span className="generation-spinner"><LoaderCircle className="spin" size={20}/></span>
        <div><small>{language === 'kk' ? 'ҚҰЖАТ ДАЙЫНДАЛУДА' : 'ДОКУМЕНТ ФОРМИРУЕТСЯ'}</small><strong>{steps[index]}</strong></div>
        <span className="generation-time">{Math.floor((generationProgress.elapsed || 0) / 60)}:{String((generationProgress.elapsed || 0) % 60).padStart(2, '0')}</span>
      </div>
      <div className="generation-progress-track"><span style={{ width: percent + '%' }}/></div>
      <div className="generation-step-list">{steps.map((label, stepIndex) => <div key={label} className={stepIndex < index ? 'done' : stepIndex === index ? 'active' : ''}><span>{stepIndex < index ? '✓' : stepIndex + 1}</span><em>{label}</em></div>)}</div>
      <p>{language === 'kk' ? 'KORGAN жұмысын жалғастырып жатыр — қосымша қатып қалған жоқ. Қайта төлеудің немесе батырманы қайта басудың қажеті жоқ.' : 'KORGAN продолжает работу — приложение не зависло. Повторно платить или нажимать кнопку ещё раз не нужно.'}</p>
    </section>;
  };

`;
source = replaceRequired(source, helperAnchor, helper + helperAnchor, 'generation progress helper');

source = replaceRequired(
  source,
  "  const generateDocument = async () => {\n    if (!activeCase || busy) return; setBusy(true); setNotice('');",
  "  const generateDocument = async () => {\n    if (!activeCase || busy) return; setBusy(true); setNotice(''); startGenerationProgress();",
  'generation progress start',
);
source = replaceRequired(
  source,
  "      if (result?.payment_required && result?.payment) { setDocPayment(result.payment); setScreen('doc-payment'); return; }",
  "      if (result?.payment_required && result?.payment) { stopGenerationProgress(); setDocPayment(result.payment); setScreen('doc-payment'); return; }",
  'generation payment stop',
);
source = replaceRequired(
  source,
  "      await refreshCases(); setScreen('ready');\n    } catch (error) { setNotice(error?.message || t.down); }\n    finally { setBusy(false); }\n  };",
  "      await refreshCases(); stopGenerationProgress(); setScreen('ready');\n    } catch (error) { stopGenerationProgress(); setNotice(error?.message || t.down); }\n    finally { setBusy(false); }\n  };",
  'generation completion stop',
);

source = replaceRequired(
  source,
  "{notice && <div className=\"warning-note\"><AlertTriangle size={17}/>{notice}</div>}<label className=\"secondary wide\"><Paperclip size={18}/>{busy ? t.processing : t.addFile}",
  "{notice && <div className=\"warning-note\"><AlertTriangle size={17}/>{notice}</div>}<GenerationStatus/><label className=\"secondary wide\"><Paperclip size={18}/>{busy ? t.processing : t.addFile}",
  'case generation status card',
);
source = replaceRequired(
  source,
  "<div className=\"payment-amount centered\">{money(docPayment.amount_kzt)}</div><section className=\"analysis-card manual-card\">",
  "<div className=\"payment-amount centered\">{money(docPayment.amount_kzt)}</div><GenerationStatus/><section className=\"analysis-card manual-card\">",
  'payment generation status card',
);

writeFileSync(mainFile, source, 'utf8');
