"use strict";
let chosen = [];
let bookingLab = "";
let preferredUnit = "";
let slotDay = "";
const slotKey = c => c.unit+"@"+c.hour;

function describeSlots(cells) {
  return cells.map(c=>unit(c.unit).name+" ("+c.unit+") "+clock(c.hour)+"–"+clock(c.hour+1)).join(", ");
}
function openBooking(u) {
  chosen=[];
  const lab=state.labs.find(l=>l.department===u.department && l.room===u.room);
  bookingLab=lab.id;preferredUnit=u.id;
  display("timetable",true);
  renderBooking();
  $("#slotDate").focus();
}
function paintSummary() {
  $("#continueBooking").disabled=$("#clearSlots").disabled=!chosen.length;
  $("#slotSummary").textContent=chosen.length ? "Selected for "+slotDay+": "+describeSlots(chosen) :
    slotDay ? "No slots selected." : "Choose a date to see available slots.";
}
function renderBooking() {
  const panel=$("#bookingPanel");
  panel.hidden=state.role!=="student";
  if(panel.hidden){chosen=[];return;}
  const date=$("#slotDate");
  date.min=state.today;date.max=state.max_day;
  if(slotDay && (slotDay<date.min || slotDay>date.max)){slotDay="";date.value="";chosen=[];}
  if(!state.labs.some(l=>l.id===bookingLab))bookingLab=state.labs[0]?.id || "";
  fillSelect($("#slotLab"),state.labs.map(l=>[l.id,l.room+" · "+l.department]));
  $("#slotLab").value=bookingLab;
  const grid=$("#slotGrid"), lab=state.labs.find(l=>l.id===bookingLab);
  const previous=grid.contains(document.activeElement)?document.activeElement.dataset.cell:null;
  grid.replaceChildren();
  if(!slotDay || !lab){paintSummary();return;}
  const weekDay=(new Date(slotDay+"T12:00:00Z").getUTCDay()+6)%7;
  const roomUnits=state.catalog.filter(u=>u.department===lab.department && u.room===lab.room && u.status!=="retired");
  roomUnits.sort((a,b)=>Number(b.id===preferredUnit)-Number(a.id===preferredUnit));
  const dayBusy=state.busy.filter(s=>s.day===slotDay);
  const classes=state.timetable.filter(c=>c.lab_id===lab.id && c.weekday===weekDay);
  const table=el("table"), head=table.createTHead().insertRow();
  table.createCaption().textContent=lab.room+" · "+slotDay+" · IST";
  const column=el("th","Equipment");column.scope="col";head.append(column);
  for(let h=9;h<17;h++){const th=el("th",clock(h)+"–"+clock(h+1));th.scope="col";head.append(th);}
  const body=table.createTBody(), available=new Set();
  for(const u of roomUnits){
    const row=body.insertRow(), label=el("th",u.name+" ("+u.id+")");label.scope="row";row.append(label);
    for(let h=9;h<17;h++){
      const cell={unit:u.id,hour:h}, key=slotKey(cell), btn=el("button");
      btn.type="button";btn.dataset.cell=key;
      const overlaps=dayBusy.filter(s=>s.hour<=h && h<s.hour+s.hours);
      const reservation=overlaps.find(s=>s.unit===u.id);
      const lesson=classes.find(c=>c.start<clock(h+1) && clock(h)<c.end);
      let style="closed", status;
      if(reservation){style="booked";status=reservation.pending?"Held":"Booked";}
      else if(h===state.lunch)status="Lunch";
      else if(weekDay>=5)status="Closed";
      else if(u.status==="maintenance")status="Maintenance";
      else if(lesson)status="Class · "+lesson.section;
      else if(slotDay===state.today && h<=Number(state.now.slice(11,13)))status="Past";
      else if(overlaps.some(s=>s.mine)){style="elsewhere";status="Your other booking";}
      else{
        available.add(key);
        const selected=chosen.some(c=>slotKey(c)===key);
        style=selected?"selected":"available";status=selected?"Selected":"Available";
        btn.setAttribute("aria-pressed",String(selected));
        btn.onclick=()=>{
          const next=selected?chosen.filter(c=>slotKey(c)!==key):[...chosen,cell];
          if(new Set(next.map(c=>c.hour)).size>2){$("#slotSummary").textContent="Choose at most two distinct hours.";return;}
          if(new Set(next.map(c=>c.unit)).size>Number($("#groupSize").value)){$("#slotSummary").textContent="Choose at most one unit per student, or increase the group size.";return;}
          chosen=next;renderBooking();
        };
      }
      btn.disabled=!available.has(key);btn.className=style;btn.textContent=status;
      btn.setAttribute("aria-label",u.name+" "+u.id+", "+clock(h)+" to "+clock(h+1)+", "+status);
      row.insertCell().append(btn);
    }
  }
  const before=chosen.length;chosen=chosen.filter(c=>available.has(slotKey(c)));
  if(before!==chosen.length){if($("#requestBox").open)$("#requestBox").close();say("Availability changed. Review your remaining selection.");}
  if(roomUnits.length)grid.append(table);else grid.append(el("p","No current equipment in this lab."));
  if(previous)Array.from(grid.querySelectorAll("button")).find(b=>b.dataset.cell===previous)?.focus({preventScroll:true});
  paintSummary();
}
$("#slotDate").onchange=e=>{slotDay=e.target.validity.valid?e.target.value:"";chosen=[];renderBooking();};
$("#slotLab").onchange=e=>{bookingLab=e.target.value;preferredUnit="";chosen=[];renderBooking();};
$("#groupSize").onchange=()=>{if(new Set(chosen.map(c=>c.unit)).size>Number($("#groupSize").value))chosen=[];renderBooking();};
$("#clearSlots").onclick=()=>{chosen=[];renderBooking();};
$("#continueBooking").onclick=()=>{
  if(!chosen.length)return;
  requestId=crypto.randomUUID();
  const f=$("#booking");prepareForm(f);
  const group=$("#groupMembers");group.replaceChildren();
  for(let i=1;i<Number($("#groupSize").value);i++){
    const fieldset=el("fieldset");fieldset.append(el("legend","Student "+(i+1)));
    for(const [key,title,max] of [["name","Student name",100],["id","Registration ID",40]]){
      const label=el("label",title),input=el("input");input.name=key+i;input.required=true;input.maxLength=max;label.append(input);fieldset.append(label);
    }
    group.append(fieldset);
  }
  $("#unitName").textContent=$("#slotLab").selectedOptions[0].text;
  $("#requestSelection").textContent=slotDay+" · "+describeSlots(chosen);
  $("#requestBox").showModal();
};
formAction($("#booking"),async f=>{
  if(!chosen.length)throw Error("Close this form and choose available slots.");
  const members=[{name:f.elements.student_name.value,registration_id:f.elements.registration_id.value}];
  for(let i=1;i<Number($("#groupSize").value);i++)members.push({name:f.elements["name"+i].value,registration_id:f.elements["id"+i].value});
  try {await api("slot-requests",{id:requestId,project:f.elements.project.value,day:slotDay,members,slots:chosen});}
  catch(error){if(error.status===409){$("#requestBox").close();await refresh();say(error.message);}throw error;}
  chosen=[];$("#requestBox").close();requestStatus="";$("#requestSearch").value="";
  await refresh();display("requests",true);say("Request received. Your selected slots are held for faculty review.");
});

const sentReminders=new Set();
function desktopReminder(key,title,body){
  if(!("Notification" in window) || Notification.permission!=="granted" || sentReminders.has(key))return;
  try{
    if(sessionStorage.getItem(key))return;
    new Notification(title,{body,tag:key});
    sentReminders.add(key);
    sessionStorage.setItem(key,"1");
  }catch{ /* The in-page reminder and calendar remain available. */ }
}
$("#enableReminders").onclick=async()=>{
  try{
    const permission=await Notification.requestPermission();
    say(permission==="granted"?"Desktop booking reminders enabled for this browser.":"Use the calendar reminder or keep LabLink open for in-page reminders.");
    renderReminders();
  }catch{say("This browser supports in-page and calendar reminders.");}
};
function renderReminders(){
  $("#enableReminders").hidden=state?.role!=="student" || !("Notification" in window) || Notification.permission!=="default";
  const panel=$("#bookingReminders"), messages=[];
  if(state?.role==="student"){
    const now=Date.now();
    for(const r of state.rows.filter(r=>r.status==="approved")){
      const hours=r.slots ? [...new Set(r.slots.map(c=>c.hour))].sort((a,b)=>a-b) : [r.assigned.hour];
      const day=r.assigned.day;
      for(const h of hours.filter(h=>!hours.includes(h-1))){
        const minutes=Math.ceil((Date.parse(day+"T"+clock(h)+":00+05:30")-now)/60000);
        if(minutes>=-4 && minutes<=15){
          const text=r.project+" · "+clock(h)+" IST · "+(minutes>0?"Starts in "+minutes+" min":"Starting now");
          messages.push(text);
          desktopReminder(["lablink-reminder",r.id,day,h,minutes>0?"before":"start"].join("-"),"LabLink booking reminder",text);
        }
      }
    }
  }
  const message=messages.length?"Booking reminder: "+messages.join(" | "):"";
  if(panel.textContent!==message)panel.textContent=message;
  panel.hidden=!message;
}
let polling=false;
async function checkUpdates(){
  if(!state || state.role!=="student" || polling || (document.hidden && !("Notification" in window && Notification.permission==="granted")))return;
  polling=true;
  try{
    const snapshot=await api("state");
    if(snapshot.role!==state.role || snapshot.now.slice(0,13)!==state.now.slice(0,13) ||
       ["rows","busy","catalog","labs","timetable"].some(k=>JSON.stringify(snapshot[k])!==JSON.stringify(state[k]))){
      const approvals=snapshot.rows.filter(r=>r.status==="approved" && state.rows.some(old=>old.id===r.id && old.status==="pending"));
      await refresh();
      if(approvals.length)say("Approved: "+approvals.map(r=>r.project).join(", ")+". View Requests for your calendar reminder.");
    }
    renderReminders();
  }catch{ /* Retry on the next poll, preserving any unfinished form. */ }
  finally{polling=false;}
}
setInterval(checkUpdates,15000);
document.addEventListener("visibilitychange",()=>{if(!document.hidden)checkUpdates();});
