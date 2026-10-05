import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './lib/monaco'; // must configure the loader before any <Editor> mounts (audit M7)
import './index.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
