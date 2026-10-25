"use strict";
// Independent location status rows; water alert are managed by monitor.js.
(function(){
  const node=id=>document.getElementById(id);
  const set=(id,value)=>{if(node(id).textContent!==String(value))node(id).textContent=String(value);};
  function render(data){
    const list=node("location-alerts");list.replaceChildren();
    for(const sensor of ["upstream","downstream"]){
      const episode=window.StormReadyModel && typeof session!=="undefined" ? session.episodes?.[sensor]:null;
      const state=sensor==="upstream"?data.summary.water_state:data.pond?.water_state;
      const value=window.StormReadyModel.currentLevel(data,sensor);
      const name=sensor==="upstream"?"Upstream chamber":"Retention pond";
      const high=sensor==="upstream"?data.settings.high_water_mm:data.settings.pond_high_water_mm;
      const row=document.createElement("div");row.className=`location-alert ${episode?"critical":state==="confirming"?"warning":""}`;
      const label=document.createElement("strong");label.textContent=name;
      const detail=document.createElement("span");detail.textContent=`${value===null?"Unavailable":value.toFixed(1)+" mm"} · alert ${high} mm · ${episode?episode.acknowledged?"acknowledged; still active":"ALERT ACTIVE":state==="confirming"?"confirming":state==="below_threshold"?"below threshold":"unknown"}`;
      row.append(label,detail);list.appendChild(row);
    }
    const count=typeof session!=="undefined"?Object.keys(session.episodes||{}).length:0;
    set("alert-count",`${count} water alert${count===1?"":"s"}`);
    set("nav-alert-count",count);
  }
  window.addEventListener("stormready:status",event=>render(event.detail));
})();
