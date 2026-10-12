const fs=require('fs'),path=require('path');
const root=path.resolve(__dirname,'..'),source=path.resolve(root,'../ielts48-writing-live-20260909');
const {publicManifest}=require(path.join(source,'frontend/build.cjs'));
const out=path.join(root,'review-ui');fs.mkdirSync(out,{recursive:true});
for(const file of ['writing-feedback.js','writing-feedback.css','writing-assignments.js'])fs.copyFileSync(path.join(source,'frontend',file),path.join(out,file));
const manifest=publicManifest(JSON.parse(fs.readFileSync(path.join(source,'shared/writing-assignments.json'),'utf8')));
fs.writeFileSync(path.join(out,'assignments.js'),'window.IELTS_WRITING_ASSIGNMENTS='+JSON.stringify(manifest).replace(/</g,'\\u003c')+';\n');
console.log('Shared lesson review UI copied; public assignment metadata only.');
