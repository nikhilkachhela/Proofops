// 14_cq7_missing_by_class  (database: proofops)
// CQ7: across all incidents, which evidence is missing most often, per fault class
MATCH (d:Diagnosis {rank: 1})
RETURN d.fault_class AS fault_class, count(*) AS incidents,
       sum(CASE WHEN d.status = 'SUPPORTED' THEN 1 ELSE 0 END) AS supported,
       sum(CASE WHEN 'TemporalPrecedence' IN d.missing THEN 1 ELSE 0 END) AS missing_timing,
       sum(CASE WHEN 'DependencyPath' IN d.missing THEN 1 ELSE 0 END) AS missing_path,
       sum(CASE WHEN 'CorroboratingSignal' IN d.missing THEN 1 ELSE 0 END) AS missing_corroboration
ORDER BY incidents DESC;
