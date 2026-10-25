"use strict";
(function(){
  const nav=document.querySelector('.sidebar nav');
  if(!nav||nav.querySelector('a[href="/incidents"]'))return;
  const link=document.createElement('a');link.href='./incidents.html';link.className='nav-item';
  const source=nav.querySelector('a[href="#reading-history"] .icon');
  if(source)link.appendChild(source.cloneNode(true));
  const label=document.createElement('span');label.textContent='Incidents & maintenance';link.appendChild(label);
  const badge=document.createElement('span');badge.className='nav-count';badge.hidden=true;link.appendChild(badge);nav.appendChild(link);
  async function update(){try{const response=await fetch('/api/workflow/summary',{cache:'no-store'});if(!response.ok)return;const data=await response.json();badge.textContent=data.open_count;badge.hidden=!data.open_count;link.setAttribute('aria-label',`Incidents and maintenance, ${data.open_count} open cases`);}catch(_error){badge.hidden=true;}}
  update();setInterval(update,5000);
})();
