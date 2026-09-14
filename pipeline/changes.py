"""Compare normalized releases without treating revised history as new observations."""

def compare_release(group, previous, current):
    if previous is None:
        return {'kind':'initial','notes':['First saved release for this source group.']}
    if group=='reliefs':
        from .isa import compare_relief_releases
        result=compare_relief_releases(previous,current)
        result['kind']='relief inventory and estimates'
        return result
    if group=='outlook':
        old={v['id']:v for v in previous.get('vintages',[])}
        new={v['id']:v for v in current.get('vintages',[])}
        if set(old)-set(new):raise ValueError('Refresh would remove an archived forecast vintage')
        return {'kind':'forecast vintages','added':sorted(set(new)-set(old)),
                'revised':[key for key in old.keys()&new.keys() if old[key]!=new[key]]}
    if group not in ('fiscal',):
        fields={'composition':['years','history','socialProtection'],'debt':['securities','auctions','calendar','totals'],'curve':['curves','realCurves','breakevenCurves'],'forecast':['cumulative','fiscalYear','vintage']}
        return {'kind':'dataset sections','changedSections':[key for key in fields.get(group,[]) if previous.get(key)!=current.get(key)],'asOfChanged':previous.get('asOf')!=current.get('asOf'),'notes':['Section comparison detects changes but does not classify every value as revision versus new observation. Inspect archived vintages.']}
    old_rows={r['date']:r for r in previous.get('observations',[])}
    new_rows={r['date']:r for r in current.get('observations',[])}
    removed=sorted(old_rows.keys()-new_rows.keys())
    if removed:raise ValueError('Previously saved observation periods disappeared: '+', '.join(removed[:6]))
    revisions=[]
    large=[]
    for date in sorted(old_rows.keys()&new_rows.keys()):
        for key,value in new_rows[date].items():
            old=old_rows[date].get(key)
            if isinstance(value,(int,float)) and isinstance(old,(int,float)) and old!=value:
                revisions.append({'period':date,'series':key,'previous':old,'current':value})
                if abs(old)>100 and abs(value-old)/abs(old)>.1:large.append(revisions[-1])
    return {'kind':'observations','addedPeriods':sorted(new_rows.keys()-old_rows.keys()),
            'revisedValues':len(revisions),'largeRevisions':large[:20],
            'largeRevisionDefinition':'More than 10% change to an existing numeric observation with absolute previous value above 100 source units. Review signal, not automatic rejection.',
            'asOfChanged':previous.get('asOf')!=current.get('asOf')}
