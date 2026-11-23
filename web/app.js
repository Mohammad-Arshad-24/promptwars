"use strict";
const $ = selector => document.querySelector(selector);
const all = selector => [...document.querySelectorAll(selector)];
const el = (tag, value, cls) => {
  const node = document.createElement(tag);
  if (value !== undefined) node.textContent = value;
  if (cls) node.className = cls;
  return node;
};
const weekdays = ["Monday","Tuesday","Wednesday","Thursday","Friday"];
let requestStatus = "";
let state, activePage = "catalog", selection, requestId;
const unit = id => state.catalog.find(item => item.id === id);
const clock = h => String(h).padStart(2, "0") + ":00";
const say = message => { $("#notice").textContent = message; };
async function api(path, data) {
  const options = data === undefined ? {} : {method:"POST", headers:{"Content-Type":"application/json","X-LabLink":"1"}, body:JSON.stringify(data)};
  const response = await fetch("/api/" + path, options);
  const result = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(typeof result.detail === "string" ? result.detail : result.detail?.[0]?.msg || "Please check the fields and try again.");
    error.status = response.status;
    throw error;
  }
  return result;
}
function button(label, action, cls="quiet") {
  const b = el("button", label, cls);
  b.type = "button";
  b.onclick = async () => {b.disabled=true; try {await action();} catch(e) {say(e.message);} finally {b.disabled=false;}};
  return b;
}
function fillSelect(select, items) {
  select.replaceChildren(...items.map(([value, label]) => new Option(label, value)));
}
function plot(canvas, kind) {
  const c = canvas.getContext("2d");
  if (!c) return;
  const w=canvas.width, h=canvas.height;
  c.clearRect(0,0,w,h);
  c.strokeStyle=kind==="hero" ? "#52796b" : "#b7cbbb";
  c.lineWidth=1;
  for (let x=0;x<w;x+=16) {c.beginPath();c.moveTo(x,0);c.lineTo(x,h);c.stroke();}
  for (let y=0;y<h;y+=16) {c.beginPath();c.moveTo(0,y);c.lineTo(w,y);c.stroke();}
  c.strokeStyle=kind==="hero" ? "#d5ef8f" : "#406759";
  c.lineWidth=2.5;
  if (kind==="hero" || kind==="Instruments") {
    if (kind!=="hero") c.strokeRect(16,10,w-32,h-20);
    c.beginPath();
    for (let x=0;x<w;x++) {
      const y=h/2 + Math.sin(x/w*Math.PI*8)*Math.cos(x/w*Math.PI*2)*h*.3;
      x===0 ? c.moveTo(x,y) : c.lineTo(x,y);
    }
    c.stroke();
  } else if (kind==="Workstations") {
    c.strokeRect(24,12,88,48);c.strokeRect(32,20,72,32);c.strokeRect(61,61,14,8);
    c.beginPath();c.moveTo(46,70);c.lineTo(91,70);c.stroke();
  } else {
    c.strokeRect(35,12,66,54);c.strokeRect(52,25,32,26);
    for(let x=41;x<=96;x+=8){c.strokeRect(x,7,2,5);c.strokeRect(x,66,2,5);}
  }
}
function display(page, focus=false) {
  activePage=page;
  for(const name of ["catalog","labs","timetable","requests","insights"]) $("#"+name).hidden=name!==page;
  all("nav button").forEach(b=>{if(b.dataset.page===page)b.setAttribute("aria-current","page");else b.removeAttribute("aria-current");});
  if(focus){const h=$("#"+page+" h2"); h.tabIndex=-1;h.focus();}
}
function catalog() {
  const search=$("#search").value.trim().toLowerCase(), dept=$("#department").value;
  const items=state.catalog.filter(u=>(state.role==="faculty" || u.status!=="retired") && (!dept||dept===u.department) &&
    matchesSelect("category",u.group) && matchesSelect("unitStatus",u.status || "active") &&
    [u.name,u.id,u.department,u.group,u.description,...u.skills].join(" ").toLowerCase().includes(search));
  $("#count").textContent=items.length+" of "+state.catalog.filter(u=>state.role==="faculty" || u.status!=="retired").length+" resources";
  const cards=items.map(u=>{
    const card=el("article",undefined,"card"), art=el("div",undefined,"plate"), canvas=el("canvas");
    canvas.width=136;canvas.height=80;canvas.setAttribute("aria-hidden","true");plot(canvas,u.group);
    art.append(el("span",u.id),canvas);
    const body=el("div",undefined,"cardbody");
    body.append(el("p",u.group,"type"),el("h3",u.name),el("p",u.department+" · "+u.room,"details"),el("p",u.description),el("p",u.skills.join(" / "),"details"));
    const opening=state.openings[u.id];
    body.append(el("p",u.status==="retired"?"Retired":u.status==="maintenance"?"Under maintenance":opening?"Next unbooked hour · "+opening.day+" "+clock(opening.hour)+" IST":"Fully booked in this window","details"));
    if(state.role==="faculty" && (state.dept==="*" || state.dept===u.department))body.append(button("Edit equipment",()=>openInventory(u)));
    if(state.role==="student" && (!u.status || u.status==="active"))body.append(button("Request access",()=>openBooking(u)));
    card.append(art,body);return card;
  });
  $("#cards").replaceChildren(...(cards.length?cards:[el("p","No equipment matches these filters.","empty")]));
}
function slotText(s,hours) {return unit(s.unit).name+" · "+s.day+" · "+clock(s.hour)+"–"+clock(s.hour+hours)+" IST";}
async function decision(r,action) {
  try {await api("requests/"+r.id+"/decision",{action,...(action==="approve"?r.proposal.slot:{})});}
  finally {await refresh();}
  const selected=$("#statusFilters [aria-pressed=true]");
  if(selected) selected.focus();
  say("Request "+({approve:"approved",decline:"declined",cancel:"cancelled"}[action])+".");
}
function queue() {
  const faculty=state.role==="faculty";
  $("#queueTitle").textContent=faculty?"Faculty approval queue":"My project requests";
  $("#queueHelp").textContent=faculty?"Earlier deadlines and time already spent waiting determine priority. Ties go to students with fewer approved hours, then the oldest request. Each proposal preserves required capabilities and the student’s availability.":"See your proposed slot and faculty decision here. A proposed slot can change until faculty approve it.";
  const query=$("#requestSearch").value.trim().toLowerCase();
  const rows=state.rows.filter(r=>(!requestStatus || r.status===requestStatus) &&
    [r.project,r.student_name,r.registration_id].some(v=>v && v.toLowerCase().includes(query)));
  for (const b of all("#statusFilters button")) {
    const status=b.dataset.status;
    const count=state.rows.filter(r=>!status || r.status===status).length;
    b.textContent=(status ? status[0].toUpperCase()+status.slice(1) : "All")+" ("+count+")";
    b.setAttribute("aria-pressed",String(status===requestStatus));
  }
  $("#requestCount").textContent=rows.length+" matching requests";
  const cards=rows.map(r=>{
    const card=el("article",undefined,"queueitem");
    card.append(el("p",r.status.toUpperCase(),"overline"),el("h3",r.project),
      el("p","Requested "+unit(r.unit).name+" · "+r.hours+" h · due "+r.deadline),
      el("p","Available "+r.earliest+" to "+r.deadline+" · "+clock(r.from_hour)+"–"+clock(r.until_hour)+" IST · "+r.skills.join(", "),"details"));
    if(r.slots){
      card.replaceChildren(el("p",r.status.toUpperCase(),"overline"),el("h3",r.project),el("p",r.earliest+" · "+describeSlots(r.slots)),el("p",r.members.length===1?"Individual booking":"Group of "+r.members.length));
      card.append(el("p",r.members.map(m=>m.name+" ("+m.registration_id+")").join(", ")));
    }
    if(!r.slots && (r.student_name || r.registration_id))card.append(el("p",[r.student_name,r.registration_id].filter(Boolean).join(" · ")));
    if(r.status==="approved" && !r.slots)card.append(el("p","Confirmed · "+slotText(r.assigned,r.hours),"proposal"));
    if(!faculty && r.status==="approved"){
      card.append(el("p","LabLink reminds you 15 minutes before and at the start of each session while this page is open. For reminders after closing it, import the calendar file.","details"));
      const link=el("a","Add calendar reminder (.ics)","quiet calendar-link");
      link.href="/api/requests/"+r.id+"/calendar";link.download="LabLink-booking.ics";card.append(link);
    }
    if(r.status==="pending" && r.slots){
      card.append(el("p","Selected slots held for faculty review.","proposal"));
      if(faculty){
        if(r.proposal.slot)card.append(button("Approve slot",()=>decision(r,"approve"),"primary"));
        card.append(button("Decline request",()=>decision(r,"decline")));
      }
    }
    if(r.status==="pending" && !r.slots) {
      const s=r.proposal.slot;
      card.append(el("p",s?"Proposed · "+slotText(s,r.hours):"Waitlisted · No feasible session fits the required skills, dates and available hours.","proposal"));
      if(s){
        if(s.unit!==r.unit)card.append(el("p","Equivalent equipment meets every selected capability and fits your time window.","details"));
        if(faculty)card.append(el("p","Effective deadline distance: "+r.proposal.effective_days+" days · Previous approved hours: "+r.proposal.previous_hours,"details"));
        if(faculty) card.append(button("Approve slot",()=>decision(r,"approve"),"primary"));
      }
      if(faculty)card.append(button("Decline request",()=>decision(r,"decline")));
    }
    if(!faculty && r.can_cancel!==false && (r.status==="pending"||r.status==="approved"))card.append(button("Cancel request",()=>decision(r,"cancel")));
    return card;
  });
  $("#queue").replaceChildren(...(cards.length?cards:[el("p","No requests match these filters.","empty")]));
}
function insights() {
  $("#period").textContent="Approved hours across five campus days, "+state.days[0]+" to "+state.days.at(-1)+". Percentages use the 40-hour campus week and count project bookings only.";
  const units=state.catalog.filter(u=>(u.status!=="retired" || state.metrics[u.id]) &&
    matchesSelect("usageDept",u.department) && matchesSelect("usageMode",state.metrics[u.id] ? "used" : "unused"));
  $("#usageCount").textContent=units.length+" matching equipment units";
  $("#metrics").replaceChildren(...units.map(u=>{
    const hours=state.metrics[u.id], node=el("div",undefined,"metric");
    const bar=el("progress");bar.max=40;bar.value=hours;bar.setAttribute("aria-label",u.name+" booked hours");
    node.append(el("h3",u.name),el("p",hours+" / 40 hours booked · "+(hours*2.5)+"%"),bar);return node;
  }));
}
async function refresh() {
  const received=await api("state");
  state=received;
  $("#who").textContent=(state.demo?"Private demo":"Campus workspace")+" · "+state.role;
  $("#switch").hidden=!state.demo;
  $("#switch").textContent=state.role==="student"?"Open faculty demo":"Return to student demo";
  const current=$("#department").value;
  fillSelect($("#department"),[["","All departments"],...[...new Set(state.catalog.map(u=>u.department))].sort().map(x=>[x,x])]);
  $("#department").value=current;
  $("#addEquipment").hidden=state.role!=="faculty";
  const departments=[...new Set(state.labs.map(l=>l.department))].sort();
  for (const id of ["labDept","usageDept"]) updateFilter(id,"All departments",departments.map(d=>[d,d]));
  updateFilter("timeLab","All labs",state.labs.map(l=>[l.id,l.room+" · "+l.department]));
  updateFilter("timeDept","All departments",[...new Set(state.timetable.map(c=>c.department))].sort().map(d=>[d,d]));
  $("#addLab").hidden=$("#addClass").hidden=state.role!=="faculty";
  $("#deptOptions").replaceChildren(...departments.map(d=>new Option(d,d)));
  catalog();queue();insights();labs();renderTimetable();renderBooking();renderReminders();display(activePage);
}
function formAction(form, action) {
  form.onsubmit=async e=>{e.preventDefault();const error=form.querySelector(".error"),b=form.querySelector("button.primary");error.textContent="";b.disabled=true;
    try{await action(form);}catch(err){error.textContent=err.message;}finally{b.disabled=false;}};
}
formAction($("#advisor"),async f=>{
  $("#advice").replaceChildren(el("p","Finding equipment…"));
  let data;
  try { data=await api("advice",{project:f.querySelector("textarea").value}); }
  finally { $("#advice").replaceChildren(); }
  const nodes=[el("p",data.mode,"type")];
  if(!data.matches.length)nodes.push(el("p","No matching equipment found. Try describing the capabilities you need."));
  for(const match of data.matches){const u=unit(match.id), d=el("div");d.append(el("h3",u.name),el("p",match.reason));
    if(state.role==="student")d.append(button("Request this unit",()=>{$("#advisorBox").close();openBooking(u)}));
    nodes.push(d);}
  $("#advice").replaceChildren(...nodes);
});
formAction($("#login"),async f=>{
  await api("access",{token:f.querySelector("input").value});f.reset();$("#accessBox").close();await refresh();say("Campus workspace opened.");
});
all(".close").forEach(b=>b.onclick=()=>b.closest("dialog").close());
all("nav button").forEach(b=>b.onclick=async()=>{
  display(b.dataset.page,true);
  if (["labs","timetable","requests"].includes(b.dataset.page)) {try {await refresh();} catch(e){say(e.message);}}
});
$("#ask").onclick=()=>$("#advisorBox").showModal();
$("#access").onclick=()=>$("#accessBox").showModal();
$("#search").oninput=()=>state&&catalog();$("#department").onchange=()=>state&&catalog();
$("#refresh").onclick=()=>refresh().then(()=>say("Queue refreshed.")).catch(e=>say(e.message));
$("#switch").onclick=async()=>{try{await api("demo/role",{role:state.role==="student"?"faculty":"student"});requestStatus="";$("#requestSearch").value="";await refresh();display("requests",true);say("Demo role changed.");}catch(e){say(e.message);}};
$("#newDemo").onclick=async()=>{try{await api("demo",{});$("#search").value="";$("#department").value="";await refresh();$("#accessBox").close();display("catalog");say("New private demo opened.");}catch(e){say(e.message);}};
$("#addEquipment").onclick=()=>openInventory();
$("#labDate").onchange=labs;
$("#labHour").onchange=labs;
$("#refreshLabs").onclick=()=>refresh().then(()=>say("Lab availability refreshed.")).catch(e=>say(e.message));
plot($("#trace"),"hero");
document.addEventListener("DOMContentLoaded",async()=>{try{try{await refresh();}catch(e){if(e.status!==401)throw e;await api("demo",{});await refresh();}}catch(e){say("Workspace could not open. "+e.message);}});


let editingRevision = 0;
function openInventory(item) {
  const form = $("#inventoryForm");
  form.reset();
  form.querySelector(".error").textContent = "";
  $("#inventoryTitle").textContent = item ? "Edit equipment" : "Add equipment";
  editingRevision = item ? item.revision || 1 : 0;
  for (const key of ["id","name","department","room","group","description","status"]) {
    if (item && item[key]) form.elements.namedItem(key).value = item[key];
  }
  form.elements.namedItem("id").readOnly = Boolean(item);
  form.elements.skills.value = item ? item.skills.join(", ") : "";
  form.elements.department.readOnly = state.dept !== "*";
  if (state.dept !== "*") form.elements.department.value = state.dept;
  function options(selector, values) {
    $(selector).replaceChildren(...[...new Set(values)].sort().map(value=>new Option(value,value)));
  }
  options("#deptOptions",state.labs.map(u=>u.department));
  const updateRooms = () => options("#roomOptions",state.labs
    .filter(u=>u.department===form.elements.department.value).map(u=>u.room));
  form.elements.department.oninput = updateRooms;
  updateRooms();
  $("#inventoryBox").showModal();
}
formAction($("#inventoryForm"), async form => {
  const values = Object.fromEntries(new FormData(form));
  values.skills = values.skills.split(",").map(s=>s.trim()).filter(Boolean);
  if (!values.skills.length || values.skills.length>5 || values.skills.some(s=>s.length>80))
    throw Error("Enter one to five capabilities, each up to 80 characters.");
  await api("inventory",{...values,revision:editingRevision});
  $("#inventoryBox").close();
  $("#search").value = "";
  $("#department").value = "";
  await refresh();
  say("Inventory saved for "+values.id+".");
});

function labs() {
  if (!state) return;
  const date = $("#labDate"), hour = $("#labHour");
  date.min = state.today;
  date.max = state.max_day;
  if (!date.value || date.value < date.min || date.value > date.max) date.value = state.today;
  if (!hour.options.length) {
    fillSelect(hour, Array.from({length:8},(_,i)=>[i+9,clock(i+9)+" to "+clock(i+10)]));
    hour.value = Math.max(9,Math.min(16,Number(state.now.slice(11,13))));
  }
  const start = Number(hour.value);
  const closed = [0,6].includes(new Date(date.value+"T12:00:00Z").getUTCDay());
  const booked = new Set(state.occupancy.filter(s=>s.day===date.value && s.hour<=start &&
    start<s.hour+s.hours).map(s=>s.unit));
  const visibleLabs = state.labs.filter(l=>matchesSelect("labDept",l.department) && matchesSelect("labAccess",l.access));
  const byRoom = new Map();
  for (const u of state.catalog.filter(u=>u.status!=="retired")) {
    const key=JSON.stringify([u.department,u.room]);
    if (!byRoom.has(key)) byRoom.set(key,[]);
    byRoom.get(key).push(u);
  }
  const weekDay=(new Date(date.value+"T12:00:00Z").getUTCDay()+6)%7;
  $("#labSummary").textContent=visibleLabs.length+" of "+state.labs.length+" labs · "+
    state.catalog.filter(u=>u.status!=="retired").length+" current equipment units campus-wide";
  const cards=visibleLabs.map(lab=>{
    const units=byRoom.get(JSON.stringify([lab.department,lab.room])) || [];
    const classes=state.timetable.filter(c=>c.lab_id===lab.id && c.weekday===weekDay &&
      c.start<clock(start+1) && clock(start)<c.end);
    const unavailable=units.filter(u=>u.status==="maintenance").length;
    const busy=units.filter(u=>booked.has(u.id)).length;
    const held=units.filter(u=>state.busy.some(s=>s.pending && s.day===date.value && s.unit===u.id && s.hour===start)).length;
    const lunch=start===state.lunch;
    const free=closed || lunch || classes.length ? 0 : units.length-unavailable-busy-held;
    const detail=el("details",undefined,"lab-room"), summary=el("summary");
    const occupancyStatus=closed?"Closed":lunch?"Lunch":classes.length?"Scheduled class":busy+" booked · "+held+" held";
    summary.append(el("strong",lab.room),el("span",lab.department,"details"),
      el("span",units.length+" units · "+occupancyStatus+" · "+free+" free","lab-count"));
    detail.append(summary,el("p","Lab number: "+(lab.number || "Not recorded")+" · Physical access: "+lab.access));
    for(const c of classes) detail.append(el("p",c.start+"–"+c.end+" IST · "+c.subject+" · "+c.department+" / "+c.section));
    if(!units.length) detail.append(el("p","No equipment assigned yet."));
    for(const u of units) {
      const line=el("div",undefined,"lab-unit");
      const status=u.status==="maintenance"?"Under maintenance":closed?"Closed":lunch?"Lunch":classes.length?"Reserved for class":booked.has(u.id)?"Booked":state.busy.some(s=>s.pending && s.day===date.value && s.unit===u.id && s.hour===start)?"Held":"Free";
      line.append(el("span",u.name+" ("+u.id+")"),el("strong",status));detail.append(line);
    }
    return detail;
  });
  $("#labList").replaceChildren(...cards);
}

function matchesSelect(id, value) {
  const selected = $("#"+id).value;
  return !selected || selected===value;
}
function updateFilter(id, label, options) {
  const select=$("#"+id), previous=select.value;
  fillSelect(select,[["",label],...options]);
  if(options.some(([v])=>String(v)===previous)) select.value=previous;
}
function canManageLab(lab) {
  return state.role==="faculty" && (state.dept==="*" || state.dept===lab.department);
}
function renderTimetable() {
  const query=$("#timeSection").value.trim().toLowerCase();
  const rooms=new Map(state.labs.map(l=>[l.id,l]));
  const slots=state.timetable.filter(c=>matchesSelect("timeDay",String(c.weekday)) &&
    matchesSelect("timeLab",c.lab_id) && matchesSelect("timeDept",c.department) && c.section.toLowerCase().includes(query))
    .sort((a,b)=>a.lab_id.localeCompare(b.lab_id)||a.weekday-b.weekday||a.start.localeCompare(b.start)||a.subject.localeCompare(b.subject));
  $("#timeCount").textContent=slots.length+" weekly classes shown across "+new Set(slots.map(c=>c.lab_id)).size+" labs";

  const visibleWeekdays=weekdays.map((day,index)=>index).filter(index=>matchesSelect("timeDay",String(index)));
  const labIds=[...new Set(state.labs.filter(l=>matchesSelect("timeLab",l.id)).map(l=>l.id))];
  const wrappers=[];

  for(const labId of labIds) {
    const lab=rooms.get(labId);
    if(!lab) continue;
    const labSlots=slots.filter(c=>c.lab_id===labId);

    const wrapper=el("section",undefined,"lab-timetable");
    wrapper.setAttribute("aria-labelledby","lab-table-"+labId);
    const heading=el("h3",lab.room+" · "+lab.department,"lab-timetable-title");
    heading.id="lab-table-"+labId;
    wrapper.append(heading);

    const grid=el("div",undefined,"timetable-grid timetable-grid-content");
    grid.setAttribute("role","table");
    grid.setAttribute("aria-label",lab.room+" complete weekly timetable, Monday to Friday, 08:00 to 17:00 IST");
    grid.style.setProperty("grid-template-columns","92px repeat("+visibleWeekdays.length+",minmax(150px,1fr))");
    grid.append(el("div","Time","timetable-head"));
    visibleWeekdays.forEach(index=>grid.append(el("div",weekdays[index],"timetable-head")));

    for(let hour=8;hour<17;hour++) {
      const time=el("div",clock(hour)+"–"+clock(hour+1),"timetable-time");
      time.setAttribute("role","rowheader");
      grid.append(time);
      visibleWeekdays.forEach(day=>{
        const classes=labSlots.filter(c=>c.weekday===day&&Number(c.start.slice(0,2))<=hour&&Number(c.end.slice(0,2))>hour);
        const cell=el("div",undefined,"timetable-cell");
        cell.setAttribute("role","cell");
        cell.setAttribute("aria-label",lab.room+", "+weekdays[day]+" "+clock(hour)+", "+(classes.length?classes.length+" class":"free period"));
        for(const c of classes) {
          const item=el("article",undefined,"timetable-class");
          item.append(el("strong",c.subject),el("span",c.start+"–"+c.end+" IST"),el("span",c.department+" · Section "+c.section));
          if(canManageLab(lab)) {
            item.append(button("Edit",()=>openClass(c)),button("Remove",async()=>{
              if(!window.confirm("Remove the weekly "+c.subject+" class?")) return;
              await api("timetable/"+c.id+"/remove/"+(c.revision||1),{});await refresh();say("Weekly class removed.");
            }));
          }
          cell.append(item);
        }
        if(!classes.length) cell.append(el("span","Free","timetable-free"));
        grid.append(cell);
      });
    }
    const scroll=el("div",undefined,"timetable-scroll");
    scroll.append(grid);
    wrapper.append(scroll);
    wrappers.push(wrapper);
  }

  $("#timeList").replaceChildren(...(wrappers.length?wrappers:[el("p","No lab timetable matches this view.")]));
}
function prepareForm(form) {
  form.reset();
  form.querySelector(".error").textContent="";
}
$("#addLab").onclick=()=>{
  const form=$("#labForm");prepareForm(form);
  form.elements.department.readOnly=state.dept!=="*";
  if(state.dept!=="*") form.elements.department.value=state.dept;
  $("#labBox").showModal();
};
formAction($("#labForm"),async form=>{
  const lab=await api("labs",Object.fromEntries(new FormData(form)));
  $("#labBox").close();$("#labDept").value="";$("#labAccess").value="";
  await refresh();say("Added "+lab.room+" to the lab directory.");
});
let currentClass;
$("#addClass").onclick=()=>openClass(null);
function openClass(entry) {
  currentClass=entry;
  $("#classTitle").textContent=entry?"Edit weekly class":"Add weekly class";
  const form=$("#classForm");prepareForm(form);
  const rooms=state.labs.filter(canManageLab);
  if(!rooms.length){say("Add a lab in Labs & occupancy before scheduling a class.");return;}
  fillSelect(form.elements.lab_id,rooms.map(l=>[l.id,l.room+" · "+l.department]));
  fillSelect(form.elements.weekday,weekdays.map((d,i)=>[i,d]));
  if(entry) {for(const key of ["lab_id","department","section","subject","weekday","start","end"]) form.elements[key].value=entry[key];}
  $("#classBox").showModal();
}
formAction($("#classForm"),async form=>{
  const values=Object.fromEntries(new FormData(form));
  values.weekday=Number(values.weekday);
  const path=currentClass?"timetable/"+currentClass.id+"/edit/"+(currentClass.revision || 1):"timetable";
  await api(path,values);
  $("#classBox").close();
  for(const id of ["timeDay","timeLab","timeDept","timeSection"]) $("#"+id).value="";
  await refresh();say("Weekly class saved. Equipment availability has been updated.");
});
updateFilter("timeDay","All weekdays",weekdays.map((d,i)=>[String(i),d]));
for(const [handler,ids] of [[catalog,["category","unitStatus"]],[labs,["labDept","labAccess"]],
  [insights,["usageDept","usageMode"]],[renderTimetable,["timeDay","timeDept","timeLab"]]]) {
  for(const id of ids) $("#"+id).onchange=()=>state && handler();
}
$("#timeSection").oninput=()=>state && renderTimetable();
$("#requestSearch").oninput=()=>state && queue();
for(const b of all("#statusFilters button")) b.onclick=()=>{
  requestStatus=b.dataset.status;if(state)queue();
};
