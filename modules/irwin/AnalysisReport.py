from collections import namedtuple
from datetime import datetime
from functools import reduce
from math import ceil
import operator
import numpy as np
import random
import pymongo
import json

class PlayerReport(namedtuple('PlayerReport', ['id', 'userId', 'owner', 'activation', 'date'])):
    @staticmethod
    def new(userId, owner, activation):
        reportId = str("%016x" % random.getrandbits(64))
        return PlayerReport(
            id=reportId,
            userId=userId,
            owner=owner,
            activation=activation,
            date=datetime.now())

    def reportDict(self, gameReports):
        return {
            'userId': self.userId,
            'owner': self.owner,
            'activation': int(self.activation),
            'games': [gameReport.reportDict() for gameReport in gameReports]
        }

class GameReportStore(namedtuple('GameReportStore', ['gameReports'])):
    @staticmethod
    def new(gameReports):
        gameReports.sort(key=lambda obj: -obj.activation)
        return GameReportStore(gameReports)

    def topGames(self, p=0.15):
        """ Get the top p games from all gameReports """
        self.gameReports.sort(key=lambda obj: -obj.activation)
        return [gameReport 
            for i, gameReport in enumerate(self.gameReports)
            if (i <= p*len(self.gameReports) or gameReport.activation >= 90)]

    def longestGame(self):
        if len(self.gameReports) == 0:
            return 0
        return max([len(gameReport.moves) for gameReport in self.gameReports])

    def losses(self, top=False):
        gameReports = self.topGames() if top else self.gameReports
        return [gameReport.losses() for gameReport in gameReports]

    def ranks(self, subNone=None, top=False):
        gameReports = self.topGames() if top else self.gameReports
        return [gameReport.ranks(subNone=subNone) for gameReport in gameReports]

    def averageLossByMove(self, top=False):
        """ Calculate the average loss by move. Used for graphing"""
        if self.longestGame() == 0:
            return [] # zero case
        return json.dumps(GameReportStore.zipAvgLOL(self.losses(top=top)))

    def averageRankByMove(self, top=False):
        """ Calculate the the average rank by move. Used for graphing """
        if self.longestGame() == 0:
            return [] # zero case
        return json.dumps(GameReportStore.zipAvgLOL(self.ranks(subNone=6, top=top)))

    def stdBracketLossByMove(self, top=False):
        if self.longestGame() == 0:
            return [] # zero case
        return json.dumps(GameReportStore.stdBracket(self.losses(top=top)))

    def stdBracketRankByMove(self, top=False):
        if self.longestGame() == 0:
            return [] # zero case
        return json.dumps(GameReportStore.stdBracket(self.ranks(subNone=6, top=top), lowerLimit=1))

    def binnedActivations(self, top=False):
        gameReports = self.topGames() if top else self.gameReports
        return json.dumps([sum([int(gameReport.activation in range(i,i+10)) for gameReport in gameReports]) for i in range(0, 100, 10)][::-1])

    def binnedMoveActivations(self, top=False):
        gameReports = self.topGames() if top else self.gameReports
        moveActivations = reduce(operator.concat, [gameReport.activations() for gameReport in gameReports])
        return json.dumps([sum([int(moveActivation in range(i,i+10)) for moveActivation in moveActivations]) for i in range(0, 100, 10)][::-1])

    def activations(self, top=False):
        gameReports = self.topGames() if top else self.gameReports
        activations = []
        [activations.extend(gr.activations()) for gr in gameReports]
        return activations
        
    @staticmethod
    def zipLOL(lol):
        """
        lol: List[List[A]]
        assumes the input isn't : []
        """
        longest = max([len(l) for l in lol])
        bins = [[] for i in range(longest)]
        for l in lol:
            try:
                [bins[i].append(l[i]) for i in range(longest) if l[i] is not None]
            except IndexError:
                continue
        return bins

    @staticmethod
    def zipAvgLOL(lol):
        """
        lol: List[List[A]]
        assumes the input isn't : []
        """
        return [np.average(b) for b in GameReportStore.zipLOL(lol)]

    @staticmethod
    def zipStdLOL(lol):
        """
        lol: List[List[A]]
        assumes the input isn't : []
        """
        return [np.std(b) for b in GameReportStore.zipLOL(lol)]

    @staticmethod
    def stdBracket(lol, lowerLimit=0):
        stds = GameReportStore.zipStdLOL(lol)
        avgs = GameReportStore.zipAvgLOL(lol)
        return {
            'top': [avg + stds[i] for i, avg in enumerate(avgs)],
            'bottom': [max(avg - stds[i], lowerLimit) for i, avg in enumerate(avgs)]
        }

class GameReport(namedtuple('GameReport', ['id', 'reportId', 'gameId', 'activation', 'moves'])):
    @staticmethod
    def new(analysedGame, gameActivation, gamePredictions, reportId, userId):
        gameId = analysedGame.gameId
        return GameReport(
            id=gameId + '/' + reportId,
            reportId=reportId,
            gameId=gameId,
            activation=gameActivation,
            moves=[MoveReport.new(am, p) for am, p in zip(analysedGame.analysedMoves, movePredictions(gamePredictions[0]))])

    def reportDict(self):
        return {
            'gameId': self.gameId,
            'activation': self.activation,
            'moves': [move.reportDict() for move in self.moves]
        }

    def colorIndex(self):
        return int(self.activation/10)

    def activations(self):
        return [move.activation for move in self.moves]

    def ranks(self, subNone=None):
        return [(subNone if move.rank is None else move.rank) for move in self.moves]

    def ranksJSON(self):
        return json.dumps(self.ranks())

    def losses(self):
        losses = [move.loss for move in self.moves]
        if losses[-1] > 50:
            losses[-1] = 0
        return losses

    def moveNumbers(self):
        return [i+1 for i in range(len(self.moves))]

    def binnedActivations(self):
        bins = [0 for i in range(10)]
        for move in self.moves:
            bins[int(move.activation/10)] += 1
        return bins[::-1]


class MoveReport(namedtuple('MoveReport', ['activation', 'rank', 'ambiguity', 'advantage', 'loss'])):
    @staticmethod
    def new(analysedMove, movePrediction):
        return MoveReport(
            activation=moveActivation(movePrediction),
            rank=analysedMove.trueRank(),
            ambiguity=analysedMove.ambiguity(),
            advantage=int(100*analysedMove.advantage()),
            loss=int(100*analysedMove.winningChancesLoss()))

    def reportDict(self):
        return {
            'a': self.activation,
            'r': self.rank,
            'm': self.ambiguity,
            'o': self.advantage,
            'l': self.loss
        }

def movePredictions(gamePredictions):
    return list(zip(list(gamePredictions[1][0]), list(gamePredictions[2][0])))

def moveActivation(movePrediction):
    return int(50*(movePrediction[0][0]+movePrediction[1][0]))

class PlayerReportBSONHandler:
    @staticmethod
    def reads(bson):
        return PlayerReport(
            id=bson['_id'],
            userId=bson['userId'],
            owner=bson['owner'],
            activation=bson['activation'],
            date=bson['date']
            )

    @staticmethod
    def writes(playerReport):
        return {
            '_id': playerReport.id,
            'userId': playerReport.userId,
            'owner': playerReport.owner,
            'activation': playerReport.activation,
            'date': playerReport.date
        }

class GameReportBSONHandler:
    @staticmethod
    def reads(bson):
        return GameReport(
            id=bson['_id'],
            reportId=bson['reportId'],
            gameId=bson['gameId'],
            activation=bson['activation'],
            moves=[MoveReportBSONHandler.reads(mBson) for mBson in bson['moves']])

    @staticmethod
    def writes(gameReport):
        return {
            '_id': gameReport.id,
            'reportId': gameReport.reportId,
            'gameId': gameReport.gameId,
            'activation': gameReport.activation,
            'moves': [MoveReportBSONHandler.writes(move) for move in gameReport.moves]
        }

class MoveReportBSONHandler:
    @staticmethod
    def reads(bson):
        return MoveReport(
            activation=bson['a'],
            rank=bson['r'],
            ambiguity=bson['m'],
            advantage=bson['o'],
            loss=bson['l'])

    @staticmethod
    def writes(moveReport):
        return {
            'a': moveReport.activation,
            'r': moveReport.rank,
            'm': moveReport.ambiguity,
            'o': moveReport.advantage,
            'l': moveReport.loss
        }

class PlayerReportDB(namedtuple('PlayerReportDB', ['playerReportColl'])):
    def byPlayerId(self, userId):
        return [PlayerReportBSONHandler.reads(bson)
            for bson
            in self.playerReportColl.find(
                filter={'userId': userId},
                sort=[('date', pymongo.DESCENDING)])]

    def newestByUserId(self, userId):
        bson = self.playerReportColl.find_one(
            filter={'userId': userId},
            sort=[('date', pymongo.DESCENDING)])
        return None if bson is None else PlayerReportBSONHandler.reads(bson)

    def byPlayerIds(self, userIds):
        return [self.newestByUserId(userId) for userId in userIds]

    def newest(self, amount=50):
        return [PlayerReportBSONHandler.reads(bson) 
            for bson in self.playerReportColl.find(sort=[('date', pymongo.DESCENDING)], limit=amount)]

    def byId(self, reportId):
        bson = self.playerReportColl.find_one({'_id': reportId})
        return None if bson is None else PlayerReportBSONHandler.reads(bson)

    def write(self, playerReport):
        self.playerReportColl.update_one(
            {'_id': playerReport.id},
            {'$set': PlayerReportBSONHandler.writes(playerReport)},
            upsert=True)

    def timeSinceUpdated(self, userId):
        report = self.newestByUserId(userId)
        if report is None:
            return None
        return datetime.now() - report.date

class GameReportDB(namedtuple('GameReportDB', ['gameReportColl'])):
    def byId(self, id):
        bson = self.gameReportColl.find_one({'_id': id})
        return None if bson is None else GameReportBSONHandler.reads(bson)

    def byReportId(self, reportId):
        return [GameReportBSONHandler.reads(bson) for bson in self.gameReportColl.find({'reportId': reportId})]

    def byGameId(self, gameId):
        return [GameReportBSONHandler.reads(bson) for bson in self.gameReportColl.find({'gameId': gameId})]

    def write(self, gameReport):
        self.gameReportColl.update_one(
            {'_id': gameReport.id},
            {'$set': GameReportBSONHandler.writes(gameReport)},
            upsert=True)

    def writeMany(self, gameReports):
        [self.write(gameReport) for gameReport in gameReports]