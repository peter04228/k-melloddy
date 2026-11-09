import fs from 'node:fs/promises';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import path from 'node:path';
const [payloadPath,modules]=process.argv.slice(2);
const require=createRequire(path.join(modules,'__runtime_resolver__.cjs'));
const {Workbook,SpreadsheetFile}=await import(pathToFileURL(require.resolve('@oai/artifact-tool')));
const payload=JSON.parse(await fs.readFile(payloadPath,'utf8'));
const wb=Workbook.create();
for(const item of payload.sheets){
 const s=wb.worksheets.add(item.name),n=item.headers.length,h=item.header_row,rows=item.rows;
 const last=String.fromCharCode(64+n);
 s.showGridLines=false;
 const range=s.getRangeByIndexes(0,0,Math.max(h+rows.length,h),n);
 range.format.font={name:'Arial',size:10};range.format.verticalAlignment='top';range.format.wrapText=true;
 for(let i=0;i<n;i++)s.getRangeByIndexes(0,i,h+rows.length,1).format.columnWidth=item.widths[i];
 s.mergeCells(`A1:${last}1`);
 s.getRange('A1').values=[[n===15 ? `K-MELLODDY 공개 DB / Dataset — 전체 ${rows.length}개 자료 항목` : item.title]];
 s.getRange(`A1:${last}1`).format.font={name:'Arial',size:16,bold:true,color:'#20354B'};
 s.getRange(`A1:${last}1`).format.rowHeight=item.title_height;
 if(h===4){
   s.mergeCells(`A2:${last}2`);
   s.getRange('A2').values=[[(payload.summary.status==='PARTIAL'?'검증 미완료: 저장된 현재 판정':'검수 결과')+' · 이 시트 '+rows.length+'편 · 전체 보류 '+payload.summary.N_pending+'편 · 미처리 '+payload.summary.incomplete_count+'편']];
   s.getRange(`A2:${last}2`).format.rowHeight=26;
   const counts=label=>rows.filter(r=>r[8]===label).length;
   s.getRange('A3:J3').values=[['전체 논문',rows.length,'포함',counts('포함'),'제외',counts('제외'),'보류',counts('보류'),'등록 공개 DB',payload.summary.confirmed_dataset_count]];
   s.getRange(`A3:${last}3`).format.rowHeight=24;
 }
 const headers=s.getRangeByIndexes(h-1,0,1,n);headers.values=[item.headers];
 headers.format={fill:'#20354B',font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},rowHeight:item.header_height,wrapText:true};
 if(rows.length){s.getRangeByIndexes(h,0,rows.length,n).values=rows;s.getRangeByIndexes(h,0,rows.length,n).format.rowHeight=55;}
 if(n===16){
  rows.forEach((row,index)=>{
   const lines=Math.max(...[7,9,10,11,12,13,14,15].map(col=>Math.ceil([...String(row[col]??'')].reduce((sum,ch)=>sum+(ch.codePointAt(0)>255?2:1),0)/Math.max(8,item.widths[col]-2))));
   s.getRangeByIndexes(h+index,0,1,n).format.rowHeight=Math.min(409,Math.max(55,lines*16+12));
  });
 }
 s.freezePanes.freezeRows(h);
}
wb.recalculate();
for(const item of payload.sheets){
 const inspected=await wb.inspect({kind:'table',range:`'${item.name}'!A1:H${item.header_row+Math.min(item.rows.length,3)}`,tableMaxRows:7,tableMaxCols:8,maxChars:2000});
 await fs.writeFile(path.join(payload.output_dir,item.name+'.inspection.json'),inspected.ndjson);
 if(payload.render){
   const preview=await wb.render({sheetName:item.name,range:`A1:F${item.header_row+Math.min(item.rows.length,3)}`,scale:1.3,format:'png'});
   await fs.writeFile(path.join(payload.output_dir,item.name+'.png'),new Uint8Array(await preview.arrayBuffer()));
    if(item.headers.length===16){
     const dataPreview=await wb.render({sheetName:item.name,range:`I4:M${item.header_row+Math.min(item.rows.length,4)}`,scale:1.3,format:'png'});
     await fs.writeFile(path.join(payload.output_dir,item.name+'.data.png'),new Uint8Array(await dataPreview.arrayBuffer()));
     const reasonPreview=await wb.render({sheetName:item.name,range:`N4:P${item.header_row+Math.min(item.rows.length,4)}`,scale:1.3,format:'png'});
     await fs.writeFile(path.join(payload.output_dir,item.name+'.reason.png'),new Uint8Array(await reasonPreview.arrayBuffer()));
    }
 }
}
const file=await SpreadsheetFile.exportXlsx(wb);await file.save(path.join(payload.output_dir,'DB_Select_Final.xlsx'));
