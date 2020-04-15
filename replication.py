from pymongo import MongoClient, ReplaceOne

import argparse
import pymongo.errors
import time

def reclen(d):
    r = 0
    for k in d:
        r = r + len(d[k])
    return r

def replicate():
    source_client = MongoClient('mongodb://docdbadmin:mytestpassword@testcluster.cluster-cjf6q8nxfefi.us-east-2.docdb.amazonaws.com:27017/?ssl=true&tlsAllowInvalidHostnames=true&ssl_ca_certs=rds-combined-ca-bundle.pem')
    target_client = MongoClient('mongodb://docdbadmin:mytestpassword@testcluster1.cluster-cjf6q8nxfefi.us-east-2.docdb.amazonaws.com:27017/?ssl=true&tlsAllowInvalidHostnames=true&ssl_ca_certs=rds-combined-ca-bundle.pem')
    track_db = 'testdb'
    track_coll = 'samplecollection'
    mydb = source_client["testdb"]
    coll = mydb.get_collection('samplecollection')
    stream = coll.watch()
    tracker = target_client[track_db][track_coll]
    tracker_doc = tracker.find_one_and_update({}, {"$setOnInsert": {"token": None}}, upsert=True)
    token = None
    ctime = None
    try:
        with coll.watch([{"$match": {"operationType": {"$in": ["insert", "update"]}}}],
                                 full_document="updateLookup",  resume_after=token) as stream:
            start = int(time.time() * 1000)
            batch = {}
            for change in stream:
                tok = change["_id"]
                clustertime = change["clusterTime"]
                ns = change["ns"]["db"] + "." + change["ns"]["coll"]
                full_doc = change["fullDocument"]

                if ns in batch:
                    batch[ns].append(ReplaceOne({"_id": full_doc["_id"]}, full_doc, upsert=True))
                else:
                    batch[ns] = [ReplaceOne({"_id": full_doc["_id"]}, full_doc, upsert=True)]

                t = int(time.time() * 1000)
                if reclen(batch) >= 100 or (t-start) > 1000: # flush every 100 docs or 1000ms
                    for ns in batch:
                        db = ns[0:ns.index(".")]
                        coll = ns[ns.index(".")+1:]
                        target_client[db][coll].bulk_write(batch[ns], ordered=False)

                    tracker.update_one({}, {"$set": {"token": tok, "clusterTime": clustertime}}, upsert=True)
                    print("Bulk insert of %d events, batch started %dms ago" % (reclen(batch), t-start))
                    batch = {}
                    start = t

    except pymongo.errors.PyMongoError as error:
        print("error: %s" % str(error))


if __name__ == "__main__":
    replicate()
