import React from 'react';
import ReactDOM from 'react-dom/client';
import Workbench from './workbench/Workbench';
import './styles/global.css';
import './features/codon/table.css';
import './features/codon/engine.css';
import './features/codon/history.css';

ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><Workbench /></React.StrictMode>);
