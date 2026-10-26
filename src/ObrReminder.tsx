import {useEffect,useState} from 'react';
import {Mail} from 'lucide-react';
import {C} from './country';

type ObrCheck={status:'current'|'outdated'|'unknown';pinned:{vintage:string};newer:{title:string;url:string;publishedAt:string}[]};
const EMAIL='p.schneider@imperial.ac.uk';

/** UK only: shown when the daily GOV.UK check finds an OBR forecast newer than the pinned vintage. */
export function ObrReminder(){
 const [check,setCheck]=useState<ObrCheck|null>(null);
 useEffect(()=>{if(C.id!=='uk')return;fetch(`${import.meta.env.BASE_URL}data/obr-check.json`,{cache:'no-store'}).then(r=>r.ok?r.json():null).then(setCheck).catch(()=>{});},[]);
 const latest=check?.status==='outdated'?check.newer.at(-1):undefined;
 if(!latest)return null;
 const body=`Hi Patrick,\n\nThe OBR has published the ${latest.title} (${latest.url}), but Fiscal Space is still on the ${check!.pinned.vintage}.\n\nTime to update the OBR data!\n\n${location.href}`;
 const mailto=`mailto:${EMAIL}?subject=${encodeURIComponent('Fiscal Space: new OBR forecast is out')}&body=${encodeURIComponent(body)}`;
 return <div className="obr-reminder" role="status"><p>The <a href={latest.url}>{latest.title}</a> is out, but the forecasts here are still from the {check!.pinned.vintage}. <strong>Tell Patrick to update the OBR data.</strong></p><a className="obr-reminder-button" href={mailto}><Mail size={14} aria-hidden="true"/>Email Patrick</a></div>;
}
